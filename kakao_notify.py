# -*- coding: utf-8 -*-
"""카카오톡 '나에게 보내기'(메모 API) 발송.

기존 로컬 버전은 카카오 MCP를 거쳤으나, GitHub Actions에는 MCP가 없으므로
카카오 REST API를 직접 호출한다.

환경변수:
  KAKAO_REST_KEY       카카오 개발자 앱의 REST API 키          (필수)
  KAKAO_REFRESH_TOKEN  talk_message 동의를 마친 리프레시 토큰   (필수)
  GH_PAT               리프레시 토큰 자동 갱신용 PAT            (선택)
  GITHUB_REPOSITORY    owner/repo — Actions가 자동 주입          (선택)

리프레시 토큰은 유효기간이 2개월이고, 남은 기간이 1개월 미만이면 카카오가
갱신 응답에 새 토큰을 실어 보내면서 기존 토큰을 폐기한다. GH_PAT가 있으면
새 토큰을 리포지토리 시크릿에 자동으로 덮어써 수동 개입을 없앤다.
"""
import json, os, sys, urllib.request, urllib.parse, urllib.error

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL  = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
GH_API    = "https://api.github.com"


def _post_form(url, data, headers=None):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers or {})
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s: %s" % (url, e.code, e.read().decode("utf-8", "replace")[:300]))


def _gh(method, path, token, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(GH_API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _rotate_secret(new_token):
    """새 리프레시 토큰을 KAKAO_REFRESH_TOKEN 시크릿에 덮어쓴다."""
    pat  = os.environ.get("GH_PAT")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not (pat and repo):
        print("[warn] 카카오가 새 리프레시 토큰을 발급했으나 GH_PAT/GITHUB_REPOSITORY가 없어 "
              "자동 갱신하지 못했습니다. KAKAO_REFRESH_TOKEN 시크릿을 아래 값으로 직접 바꾸세요:\n"
              "  %s" % new_token, file=sys.stderr)
        return False
    try:
        from base64 import b64encode
        from nacl import encoding, public
    except ImportError:
        print("[warn] pynacl 미설치로 시크릿 자동 갱신 실패. 새 토큰: %s" % new_token, file=sys.stderr)
        return False
    key = _gh("GET", "/repos/%s/actions/secrets/public-key" % repo, pat)
    sealed = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder))
    _gh("PUT", "/repos/%s/actions/secrets/KAKAO_REFRESH_TOKEN" % repo, pat,
        {"encrypted_value": b64encode(sealed.encrypt(new_token.encode("utf-8"))).decode(),
         "key_id": key["key_id"]})
    print("[info] KAKAO_REFRESH_TOKEN 시크릿을 새 토큰으로 갱신했습니다.", file=sys.stderr)
    return True


def access_token():
    rest_key = os.environ.get("KAKAO_REST_KEY")
    refresh  = os.environ.get("KAKAO_REFRESH_TOKEN")
    if not (rest_key and refresh):
        raise RuntimeError("KAKAO_REST_KEY / KAKAO_REFRESH_TOKEN 미설정")
    res = _post_form(TOKEN_URL, {"grant_type": "refresh_token",
                                 "client_id": rest_key, "refresh_token": refresh})
    if res.get("refresh_token") and res["refresh_token"] != refresh:
        try:
            _rotate_secret(res["refresh_token"])
        except Exception as e:
            print("[warn] 시크릿 갱신 실패: %s / 새 토큰: %s" % (e, res["refresh_token"]), file=sys.stderr)
    return res["access_token"]


def send(text, link_url=""):
    """텍스트 템플릿으로 나에게 보내기. text는 200자 제한."""
    link = {}
    if link_url:
        link = {"web_url": link_url, "mobile_web_url": link_url}
    obj = {"object_type": "text", "text": text[:200], "link": link}
    if link_url:
        obj["button_title"] = "공고 보기"
    res = _post_form(SEND_URL,
                     {"template_object": json.dumps(obj, ensure_ascii=False)},
                     {"Authorization": "Bearer " + access_token()})
    if res.get("result_code") not in (0, None):
        raise RuntimeError("카카오 발송 실패: %s" % res)
    return res


if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "[나라장터] 연결 테스트"
    url = sys.argv[2] if len(sys.argv) > 2 else ""
    print(send(msg, url))
