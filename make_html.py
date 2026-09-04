# -*- coding: utf-8 -*-
"""last_hits.json -> docs/index.html (GitHub Pages 공개용)"""
import json, os, re, html
from datetime import datetime, timedelta, timezone

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DIR, "docs", "index.html")
KST = timezone(timedelta(hours=9))


def load(name, default):
    p = os.path.join(DIR, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def dt(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", s or "")
    return datetime(*map(int, m.groups())) if m else None


def fmt(s):
    d = dt(s)
    if not d:
        return "—"
    return "%d.%d(%s) %02d:%02d" % (d.month, d.day, "월화수목금토일"[d.weekday()], d.hour, d.minute)


def won(v):
    try:
        n = int(float(v))
    except Exception:
        return ""
    if n >= 100000000:
        return "%.1f억" % (n / 100000000)
    if n >= 10000:
        return "%d만" % (n // 10000)
    return "{:,}".format(n)


E = html.escape


def render():
    hits = load("last_hits.json", [])
    meta = load("last_meta.json", {})
    now  = datetime.now(KST).replace(tzinfo=None)
    gen  = meta.get("generated") or now.isoformat(timespec="minutes")
    win  = meta.get("window") or []

    rows = []
    for h in hits:
        cls = dt(h.get("입찰마감", ""))
        dday, urg = "", ""
        if cls:
            n = (cls.date() - now.date()).days
            dday = "마감" if n < 0 else ("오늘 마감" if n == 0 else "D-%d" % n)
            urg  = "urgent" if n <= 3 else ""
        lic = [x.split("/")[0] for x in (h.get("면허") or [])]
        chips = "".join('<span class="chip">%s</span>' % E(x) for x in lic[:2])
        budget = won(h.get("예산", ""))
        url = h.get("URL") or ""
        rows.append("""
      <li class="row">
        <a class="rowlink" href="%s" target="_blank" rel="noopener">
          <span class="nm">%s</span>
          <span class="inst">%s</span>
          <span class="start"><span class="lbl">입찰시작</span>%s</span>
        </a>
        <div class="meta">
          <span class="dday %s">%s</span>
          <span class="mut">마감 %s</span>
          %s
          %s
        </div>
      </li>""" % (
            E(url), E(h.get("공고명", "")), E(h.get("공고기관", "")),
            E(fmt(h.get("입찰시작", ""))), urg, E(dday), E(fmt(h.get("입찰마감", ""))),
            ('<span class="mut">예산 %s</span>' % E(budget)) if budget else "",
            chips))

    body = "\n".join(rows) if rows else """
      <li class="empty"><p>새로 올라온 공고가 없습니다.</p>
      <p class="mut">다음 스캔은 오전 8시 또는 오후 6시입니다.</p></li>"""

    sub = "%s 기준 · %d건" % (gen.replace("T", " ")[:16], len(hits))
    if len(win) == 2:
        f = lambda s: "%s.%s %s:%s" % (s[4:6], s[6:8], s[8:10], s[10:12])
        sub += " · 조회 %s ~ %s" % (f(win[0]), f(win[1]))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(
        TPL.replace("{{SUB}}", E(sub)).replace("{{ROWS}}", body))
    return OUT


TPL = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>나라장터 회계용역 공고</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600&family=Noto+Serif+KR:wght@600;700&display=swap">
<style>
:root{
  --ground:#FBFAF8; --surface:#FFFFFF; --ink:#16202B; --muted:#66727F;
  --accent:#0B4F8A; --signal:#B4471F; --line:#E4E3DE; --chip:#EDF2F8;
}
@media (prefers-color-scheme: dark){
  :root{
    --ground:#12161A; --surface:#1A1F25; --ink:#E8EAED; --muted:#93A0AD;
    --accent:#7FB3E0; --signal:#E5946B; --line:#2A3138; --chip:#232B33;
  }
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans KR",-apple-system,"Malgun Gothic",sans-serif;
  font-size:15px; line-height:1.5; -webkit-text-size-adjust:100%;
}
.wrap{max-width:960px; margin:0 auto; padding:28px 18px 56px}
header{border-bottom:2px solid var(--ink); padding-bottom:14px; margin-bottom:4px}
h1{
  font-family:"Noto Serif KR",serif; font-weight:700; font-size:clamp(21px,4.6vw,29px);
  margin:0 0 6px; letter-spacing:-.01em; text-wrap:balance;
}
.sub{color:var(--muted); font-size:13px; font-variant-numeric:tabular-nums}
ul{list-style:none; margin:0; padding:0}
.row{border-bottom:1px solid var(--line); padding:15px 2px}
.rowlink{
  display:grid; gap:3px 16px; text-decoration:none; color:inherit;
  grid-template-columns:1fr; align-items:baseline;
}
.nm{font-weight:600; font-size:16px; line-height:1.4; text-wrap:pretty}
.rowlink:hover .nm, .rowlink:focus-visible .nm{color:var(--accent); text-decoration:underline; text-underline-offset:3px}
.rowlink:focus-visible{outline:2px solid var(--accent); outline-offset:4px; border-radius:3px}
.inst{color:var(--muted); font-size:13.5px}
.start{color:var(--accent); font-weight:500; font-size:13.5px; font-variant-numeric:tabular-nums}
.lbl{color:var(--muted); font-weight:400; font-size:11px; letter-spacing:.06em; margin-right:6px}
.meta{display:flex; flex-wrap:wrap; gap:6px 12px; margin-top:8px; font-size:12px; align-items:center}
.mut{color:var(--muted); font-variant-numeric:tabular-nums}
.dday{
  font-weight:600; font-size:11px; letter-spacing:.04em; color:var(--muted);
  border:1px solid var(--line); border-radius:2px; padding:2px 7px;
}
.dday.urgent{color:var(--signal); border-color:var(--signal)}
.chip{
  background:var(--chip); color:var(--accent); font-size:11px; font-weight:500;
  padding:2px 8px; border-radius:2px;
}
.empty{padding:52px 8px; text-align:center; color:var(--ink)}
.empty p{margin:0 0 6px}
footer{margin-top:26px; color:var(--muted); font-size:12px; line-height:1.7}
@media (min-width:720px){
  .rowlink{grid-template-columns:1fr 210px 150px; gap:0 20px}
  .inst,.start{text-align:left; font-size:13px}
  .lbl{display:none}
  .row{padding:13px 2px}
}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>나라장터 회계용역 공고</h1>
    <div class="sub">{{SUB}}</div>
  </header>
  <ul>{{ROWS}}</ul>
  <footer>
    공고명을 누르면 나라장터 공고문으로 이동합니다.<br>
    검색조건 — 공고명 키워드(회계·감사·세무·재무·원가·운송원가·경영진단·가치평가·자문) 또는 참가면허(회계법인·공인회계사사무소·세무법인·원가검토기관).<br>
    매일 08:00 · 18:00(KST) GitHub Actions 자동 실행. 누적 이력은 리포지토리의 history.csv에 있습니다.
  </footer>
</div>
</body>
</html>
"""

if __name__ == "__main__":
    print(render())
