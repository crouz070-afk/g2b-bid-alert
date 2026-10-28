# -*- coding: utf-8 -*-
"""카카오톡 '나에게 보내기'(메모 API) 발송.

환경변수:
  KAKAO_REST_KEY        카카오 개발자 앱의 REST API 키                 (필수)
  KAKAO_REFRESH_TOKEN   talk_message 동의를 마친 리프레시 토큰          (필수, 최초값)
  KAKAO_TOKEN_KEY       리프레시 토큰 암호화 키(base64 32바이트)        (권장)
  KAKAO_CLIENT_SECRET   앱에서 Client Secret을 켠 경우에만               (선택)

리프레시 토큰은 유효기간이 2개월이고, 남은 기간이 1개월 미만이면 카카오가 갱신 응답에
새 토큰을 실어 보내면서 기존 토큰을 폐기한다. 새 토큰은 KAKAO_TOKEN_KEY로 암호화해
kakao_token.enc에 저장하고(워크플로가 커밋), 다음 실행부터 그 값을 쓴다.
공개 리포지토리여도 키 없이는 풀 수 없다. 시크릿을 새 토큰으로 다시 등록하면 그 값이 우선 시도된다.
"""
import base64, json, os, sys, urllib.request, urllib.parse, urllib.error

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL  = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
DIR       = os.path.dirname(os.path.abspath(__file__))
ENC_F     = os.path.join(DIR, "kakao_token.enc")


def _post_form(url, data, headers=None):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers or {})
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s: %s" % (url, e.code, e.read().decode("utf-8", "replace")[:300]))


def _box():
    key = os.environ.get("KAKAO_TOKEN_KEY")
    if not key:
        return None
    from nacl.secret import SecretBox
    return SecretBox(base64.b64decode(key))


def _load_rotated():
    box = _box()
    if not (box and os.path.exists(ENC_F)):
        return None
    try:
        data = json.loads(box.decrypt(base64.b64decode(open(ENC_F).read().strip())).decode("utf-8"))
        return data
    except Exception as e:
        print("[warn] kakao_token.enc 복호화 실패: %s" % e, file=sys.stderr)
        return None


def _save_rotated(token, seed):
    box = _box()
    if not box:
        print("[warn] 카카오가 새 리프레시 토큰을 발급했으나 KAKAO_TOKEN_KEY가 없어 저장하지 못했습니다. "
              "KAKAO_REFRESH_TOKEN 시크릿을 새로 발급받아 교체해야 합니다.", file=sys.stderr)
        return
    raw = json.dumps({"refresh_token": token, "seed": seed[-12:]}).encode("utf-8")
    open(ENC_F, "w").write(base64.b64encode(box.encrypt(raw)).decode())
    print("[info] 새 리프레시 토큰을 kakao_token.enc에 저장했습니다.", file=sys.stderr)


def access_token():
    rest_key = os.environ.get("KAKAO_REST_KEY")
    seed     = os.environ.get("KAKAO_REFRESH_TOKEN") or ""
    if not (rest_key and seed):
        raise RuntimeError("KAKAO_REST_KEY / KAKAO_REFRESH_TOKEN 미설정")

    # 시크릿을 새로 등록했으면(seed가 바뀌었으면) 그 값을 먼저, 아니면 갱신 저장본을 먼저 쓴다
    rot = _load_rotated()
    cands = [seed]
    if rot and rot.get("seed") == seed[-12:]:
        cands = [rot["refresh_token"], seed]

    last = None
    for refresh in cands:
        data = {"grant_type": "refresh_token", "client_id": rest_key, "refresh_token": refresh}
        if os.environ.get("KAKAO_CLIENT_SECRET"):
            data["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"]
        try:
            res = _post_form(TOKEN_URL, data)
        except RuntimeError as e:
            last = e
            continue
        if res.get("refresh_token") and res["refresh_token"] != refresh:
            _save_rotated(res["refresh_token"], seed)
        return res["access_token"]
    raise RuntimeError("카카오 토큰 갱신 실패(리프레시 토큰 만료 가능): %s" % last)


def send(text, link_url=""):
    """텍스트 템플릿으로 나에게 보내기. 링크는 '전체 현황' 버튼이 된다.
    링크 도메인은 카카오 앱의 플랫폼(Web) 사이트 도메인에 등록돼 있어야 한다."""
    link = {"web_url": link_url, "mobile_web_url": link_url} if link_url else {}
    tok = access_token()

    def _send(t):
        obj = {"object_type": "text", "text": t, "link": link}
        if link_url:
            obj["button_title"] = "전체 현황"
        return _post_form(SEND_URL, {"template_object": json.dumps(obj, ensure_ascii=False)},
                          {"Authorization": "Bearer " + tok})

    try:
        res = _send(text[:2000])
    except RuntimeError:
        res = _send(text[:190] + "…")    # 길이 거절 대비: 앞부분만이라도 보낸다
    if res.get("result_code") not in (0, None):
        raise RuntimeError("카카오 발송 실패: %s" % res)
    return res


if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "[나라장터] 연결 테스트"
    url = sys.argv[2] if len(sys.argv) > 2 else ""
    print(send(msg, url))
