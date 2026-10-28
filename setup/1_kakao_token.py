# -*- coding: utf-8 -*-
"""카카오 리프레시 토큰 받기 — 브라우저에서 '동의하기' 한 번만 누르면 끝.

실행:  python setup/1_kakao_token.py

하는 일:
  1. 카카오 REST API 키를 물어본다(한 번만).
  2. 동의 화면을 브라우저로 연다.
  3. 로컬 5000포트로 돌아오는 인증코드를 받아 리프레시 토큰으로 교환한다.
  4. setup/.env 에 저장한다(git에 올라가지 않음).

사전 준비(카카오 개발자센터에서 한 번):
  - 앱 > 카카오 로그인 > Redirect URI 에  http://localhost:5000/oauth  등록
  - 앱 > 카카오 로그인 > 동의항목 > '카카오톡 메시지 전송' 사용 설정
  - 앱 > 플랫폼 > Web 사이트 도메인에  https://<깃허브ID>.github.io  와  https://www.g2b.go.kr  등록
    (카톡 '전체 현황' 버튼 링크는 등록된 도메인만 열린다)
  - 통화녹음 알림(C:/CallRec)과 같은 앱을 쓰면 서로의 토큰이 폐기되므로 나라장터 전용 앱을 만든다.
"""
import json, os, sys, threading, urllib.parse, urllib.request, urllib.error, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT     = 5000
REDIRECT = "http://localhost:%d/oauth" % PORT
DIR      = os.path.dirname(os.path.abspath(__file__))
ENV_F    = os.path.join(DIR, ".env")

result = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        result["code"]  = (q.get("code") or [""])[0]
        result["error"] = (q.get("error_description") or q.get("error") or [""])[0]
        ok = bool(result["code"])
        msg = "인증 완료. 이 창을 닫고 터미널로 돌아가세요." if ok else "실패: %s" % result["error"]
        page = ("<meta charset='utf-8'><body style=\"font-family:sans-serif;padding:60px;"
                "text-align:center\"><h2>%s</h2></body>" % msg).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, *a):
        pass


def post_form(url, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body)
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit("카카오 응답 오류 %s\n%s" % (e.code, e.read().decode("utf-8", "replace")))


def load_env():
    env = {}
    if os.path.exists(ENV_F):
        for ln in open(ENV_F, encoding="utf-8"):
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def save_env(env):
    with open(ENV_F, "w", encoding="utf-8") as f:
        f.write("# 이 파일은 git에 올라가지 않습니다. 시크릿 등록용 임시 보관.\n")
        for k, v in env.items():
            f.write("%s=%s\n" % (k, v))


def main():
    env = load_env()
    rest_key = env.get("KAKAO_REST_KEY") or ""
    if not rest_key:
        print("카카오 개발자센터 > 내 애플리케이션 > 앱 키 > 'REST API 키'를 붙여넣으세요.")
        rest_key = input("REST API 키: ").strip()
    if not rest_key:
        raise SystemExit("키가 비어 있습니다.")
    secret = env.get("KAKAO_CLIENT_SECRET", "")
    if "KAKAO_CLIENT_SECRET" not in env:
        print("앱 > 카카오 로그인 > 보안 에서 Client Secret을 '사용함'으로 켜 둔 경우에만 코드를 붙여넣으세요.")
        secret = input("Client Secret (없으면 그냥 Enter): ").strip()

    auth = ("https://kauth.kakao.com/oauth/authorize?"
            + urllib.parse.urlencode({"client_id": rest_key, "redirect_uri": REDIRECT,
                                      "response_type": "code", "scope": "talk_message"}))

    print("\n브라우저에서 카카오 동의 화면을 엽니다. '동의하고 계속하기'를 누르세요.")
    print("창이 안 뜨면 아래 주소를 직접 여세요:\n  %s\n" % auth)

    srv = HTTPServer(("localhost", PORT), Handler)
    threading.Timer(1.0, lambda: webbrowser.open(auth)).start()
    print("대기 중... (브라우저에서 동의하면 자동으로 진행됩니다)")
    srv.serve_forever()
    srv.server_close()

    if not result.get("code"):
        raise SystemExit("인증코드를 받지 못했습니다: %s" % result.get("error", "알 수 없음"))

    form = {"grant_type": "authorization_code", "client_id": rest_key,
            "redirect_uri": REDIRECT, "code": result["code"]}
    if secret:
        form["client_secret"] = secret
    tok = post_form("https://kauth.kakao.com/oauth/token", form)
    if not tok.get("refresh_token"):
        raise SystemExit("리프레시 토큰이 없습니다: %s" % tok)

    env["KAKAO_REST_KEY"] = rest_key
    env["KAKAO_REFRESH_TOKEN"] = tok["refresh_token"]
    env["KAKAO_CLIENT_SECRET"] = secret
    save_env(env)

    days = int(tok.get("refresh_token_expires_in", 0)) // 86400
    print("\n완료. setup/.env 에 저장했습니다. (리프레시 토큰 유효기간 약 %d일)" % days)

    # 바로 테스트 발송
    try:
        obj = {"object_type": "text", "text": "[나라장터] 연결 테스트입니다. 이 메시지가 보이면 설정 완료.",
               "link": {}}
        req = urllib.request.Request("https://kapi.kakao.com/v2/api/talk/memo/default/send",
                                     data=urllib.parse.urlencode(
                                         {"template_object": json.dumps(obj, ensure_ascii=False)}).encode("utf-8"))
        req.add_header("Authorization", "Bearer " + tok["access_token"])
        req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        print("테스트 메시지를 보냈습니다. 카카오톡 '나와의 채팅'을 확인하세요.")
    except Exception as e:
        print("테스트 발송 실패(토큰은 정상 저장됨): %s" % e)


if __name__ == "__main__":
    if sys.version_info < (3, 7):
        raise SystemExit("python 3.7 이상이 필요합니다.")
    main()
