# -*- coding: utf-8 -*-
"""진행 중 공고 전체 -> docs/index.html (GitHub Pages 공개용)

g2b_scan.py가 부른다. 최신 공고순(게시일시 내림차순)으로, 게시일별로 묶어 보여준다.
데이터는 페이지에 JSON으로 박아 넣고, 신규·남은 날짜 표시는 브라우저가 여는 시각 기준으로 계산한다.
"""
import hashlib, json, os, re

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DIR, "docs", "index.html")


def _won(v):
    try:
        n = int(float(v))
    except Exception:
        return ""
    if n <= 0:
        return ""
    if n >= 100000000:
        return "%.1f억" % (n / 100000000)
    if n >= 10000:
        return "{:,}만".format(n // 10000)
    return "{:,}원".format(n)


def _iso(s):
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})", s or "")
    return "%sT%s" % m.groups() if m else ""


def _rows(active):
    from g2b_scan import due_of
    rows = []
    for n in sorted(active, key=lambda n: n.get("posted") or n["found"], reverse=True):
        rows.append({"t": n["title"], "o": n["org"], "d": n["dem"] if n["dem"] != n["org"] else "",
                     "b": n["biz"], "p": _iso(n.get("posted")) or _iso(n["found"]),
                     "due": due_of(n).strftime("%Y-%m-%dT%H:%M"),
                     "dk": "마감" if n.get("close") else ("개찰" if n.get("open") else "기한"),
                     "m": n["method"], "w": _won(n["budget"]),
                     "k": n["kw"], "l": [x.split("/")[0] for x in n["lic"]],
                     "u": n["url"], "f": _iso(n["found"]), "c": _iso(n.get("changed", "")),
                     "no": n["no"]})
    return rows


def digest(active):
    """페이지 내용 지문 — 바뀌었을 때만 다시 배포하려고 쓴다."""
    return hashlib.sha1(json.dumps(_rows(active), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def render(active, now):
    data = {"gen": now.strftime("%Y-%m-%dT%H:%M"), "rows": _rows(active)}
    page = TEMPLATE.replace("{{DATA}}", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(page)
    return OUT


TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>나라장터 진행 중 공고</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1b1f24;--sub:#5d6670;--line:#e3e6ea;--accent:#2457c5;
--new:#d9480f;--newbg:#fff1e8;--hot:#c92a2a;--hotbg:#fff0f0;--chip:#eef1f5;--chg:#7048e8;--chgbg:#f3f0ff}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--card:#1a1e24;--ink:#e8eaed;--sub:#9aa3ad;--line:#2b3138;
--accent:#7aa2ff;--new:#ff9a5c;--newbg:#3a2418;--hot:#ff7b7b;--hotbg:#3a1c1c;--chip:#262c33;--chg:#b197fc;--chgbg:#2a2440}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;-webkit-text-size-adjust:100%;word-break:keep-all;overflow-wrap:anywhere}
.wrap{max-width:760px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:4px 0 2px}
.meta{color:var(--sub);font-size:13px}
.stats{display:flex;gap:8px;margin:14px 0 10px;flex-wrap:wrap}
.stat{flex:1 1 0;min-width:96px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;cursor:pointer;text-align:left;color:inherit;font:inherit}
.stat b{display:block;font-size:20px}
.stat span{color:var(--sub);font-size:12px}
.stat.on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
input[type=search]{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);font:inherit;margin-bottom:6px}
.day{margin:18px 0 6px;font-size:13px;font-weight:700;color:var(--sub)}
.day.hot{color:var(--hot)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:8px 0}
.card a.t{color:var(--ink);text-decoration:none;font-weight:600;font-size:15.5px}
.card a.t:hover{color:var(--accent);text-decoration:underline}
.row{display:flex;flex-wrap:wrap;gap:4px 10px;color:var(--sub);font-size:13px;margin-top:4px}
.badges{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:4px}
.bd{font-size:11px;font-weight:700;padding:1px 7px;border-radius:999px;background:var(--chip);color:var(--sub)}
.bd.new{background:var(--newbg);color:var(--new)}
.bd.hot{background:var(--hotbg);color:var(--hot)}
.bd.chg{background:var(--chgbg);color:var(--chg)}
.due{font-weight:700;color:var(--ink)}
.due.hot{color:var(--hot)}
.empty{color:var(--sub);text-align:center;padding:40px 0}
footer{color:var(--sub);font-size:12px;margin:24px 0 8px;line-height:1.6}
</style>
</head>
<body>
<div class="wrap">
  <h1>나라장터 진행 중 공고</h1>
  <div class="meta" id="meta"></div>
  <div class="stats">
    <button class="stat on" data-f="all"><b id="c-all">0</b><span>진행 중 전체</span></button>
    <button class="stat" data-f="new"><b id="c-new">0</b><span>신규 (24시간)</span></button>
    <button class="stat" data-f="today"><b id="c-today">0</b><span>오늘 게시</span></button>
  </div>
  <input type="search" id="q" placeholder="공고명·기관 검색">
  <div id="list"></div>
  <footer>회계·감사·세무·재무·원가·경영진단·가치평가·자문 키워드 또는 회계법인·공인회계사·세무법인·원가검토기관 면허제한 공고.
  마감이 지나거나 취소된 공고는 자동으로 빠집니다. 공고명을 누르면 나라장터 공고로 이동합니다. 공고번호로도 검색됩니다.</footer>
</div>
<script>
const D = {{DATA}};
const WD = "일월화수목금토";
const now = new Date();
const P = s => s ? new Date(s + ":00+09:00") : null;
const gen = P(D.gen);
const kst = d => new Date(d.getTime() + 9 * 3600e3);          // KST 달력 계산용
const dayKey = d => kst(d).toISOString().slice(0, 10);
const md = d => { const k = kst(d); return (k.getUTCMonth()+1) + "/" + k.getUTCDate() + "(" + WD[k.getUTCDay()] + ")"; };
const hm = d => kst(d).toISOString().slice(11, 16);
const dd = d => Math.round((Date.parse(dayKey(d)) - Date.parse(dayKey(now))) / 864e5);
const esc = s => String(s || "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

const rows = D.rows.map(r => Object.assign(r, {p_: P(r.p), due_: P(r.due), f_: P(r.f), c_: P(r.c)}))
  .filter(r => r.due_ >= now)
  .sort((a, b) => b.p_ - a.p_);
rows.forEach(r => {
  r.isNew = r.f_ && (now - r.f_) < 24 * 3600e3;
  r.isToday = dayKey(r.p_) === dayKey(now);
  r.isChg = r.c_ && (now - r.c_) < 3 * 24 * 3600e3;
});

document.getElementById("meta").textContent =
  "갱신 " + md(gen) + " " + hm(gen) + " · 최신 공고순 · 평일 업무시간 5분마다 확인";
document.getElementById("c-all").textContent = rows.length;
document.getElementById("c-new").textContent = rows.filter(r => r.isNew).length;
document.getElementById("c-today").textContent = rows.filter(r => r.isToday).length;

let filt = "all";
function draw() {
  const q = document.getElementById("q").value.trim().toLowerCase();
  const xs = rows.filter(r => (filt === "all" || (filt === "new" && r.isNew) || (filt === "today" && r.isToday))
    && (!q || (r.t + " " + r.o + " " + r.d + " " + r.no).toLowerCase().includes(q)));
  let html = "", last = "";
  for (const r of xs) {
    const k = dayKey(r.p_), n = -dd(r.p_);
    if (k !== last) {
      const lab = n === 0 ? "오늘" : n === 1 ? "어제" : n + "일 전";
      html += '<div class="day' + (n === 0 ? " hot" : "") + '">' + md(r.p_) + " 게시 · " + lab + "</div>";
      last = k;
    }
    const b = [];
    if (r.isNew) b.push('<span class="bd new">NEW</span>');
    if (r.isChg) b.push('<span class="bd chg">정정</span>');
    b.push('<span class="bd">' + esc(r.b) + "</span>");
    r.l.forEach(x => b.push('<span class="bd">' + esc(x) + "</span>"));
    if (!r.l.length) r.k.forEach(x => b.push('<span class="bd">' + esc(x) + "</span>"));
    html += '<div class="card"><div class="badges">' + b.join("") + "</div>"
      + '<a class="t" href="' + esc(r.u) + '" target="_blank" rel="noopener">' + esc(r.t) + "</a>"
      + '<div class="row"><span class="due">' + hm(r.p_) + " 게시</span>"
      + (r.w ? "<span>" + r.w + "</span>" : "") + (r.m ? "<span>" + esc(r.m) + "</span>" : "")
      + "<span>" + esc(r.no) + "</span></div>"
      + '<div class="row"><span>' + esc(r.o) + (r.d ? " → " + esc(r.d) : "") + "</span>"
      + "<span>" + r.dk + " " + md(r.due_) + "</span></div></div>";
  }
  document.getElementById("list").innerHTML = html || '<div class="empty">해당 공고가 없습니다.</div>';
}
document.querySelectorAll(".stat").forEach(b => b.onclick = () => {
  document.querySelectorAll(".stat").forEach(x => x.classList.remove("on"));
  b.classList.add("on"); filt = b.dataset.f; draw();
});
document.getElementById("q").oninput = draw;
draw();
</script>
</body>
</html>
"""
