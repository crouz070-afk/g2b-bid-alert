# -*- coding: utf-8 -*-
"""나라장터 공고 알림 (조달청 공공데이터포털 입찰공고정보서비스)

매시 실행된다. 매칭 공고를 notices.json에 누적해 '진행 중 공고 전체'를 유지하고,
docs/index.html(전체 현황 페이지)을 다시 만든 뒤 카카오톡으로 알린다.
  - 신규 공고가 있으면 그 시각에 바로 알림
  - 매일 아침(digest_hour) 첫 실행에는 신규가 없어도 전체 현황 요약 1통

GitHub Actions / 로컬 공용. 시각은 항상 KST 기준으로 계산한다.

사용법:
  python g2b_scan.py                  # 직전 실행 이후 스캔, 상태·페이지 갱신(발송 없음)
  python g2b_scan.py --notify         # 위 + 카카오톡 발송
  python g2b_scan.py --hours 24 --dry # 상태·발송 없이 테스트(결과만 출력)
  python g2b_scan.py --digest         # 아침 현황을 지금 만든다(--notify와 함께면 발송)

환경변수:
  G2B_SERVICE_KEY       공공데이터포털 서비스키(필수, config.json 값보다 우선)
  KAKAO_*               kakao_notify.py 참고 (--notify 시 필수)
"""
import urllib.request, urllib.parse, json, os, sys, csv, re, time
from datetime import datetime, timedelta, timezone

BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/"
DIR  = os.path.dirname(os.path.abspath(__file__))
CFG  = json.load(open(os.path.join(DIR, "config.json"), encoding="utf-8"))
STATE_F   = os.path.join(DIR, "state.json")
NOTICES_F = os.path.join(DIR, "notices.json")
HIST_F    = os.path.join(DIR, "history.csv")

OPS = {"Servc": "용역", "Thng": "물품", "Cnstwk": "공사", "Etc": "기타"}
KST = timezone(timedelta(hours=9))
WD  = "월화수목금토일"

SERVICE_KEY = os.environ.get("G2B_SERVICE_KEY") or CFG.get("serviceKey") or ""


def now_kst():
    """러너는 UTC이므로 항상 KST로 환산한다. 이후 비교를 위해 naive로 돌려준다."""
    return datetime.now(KST).replace(tzinfo=None)


def _pat(s):
    """2글자 키워드는 공백 불허(‘제16회 계룡’→‘회계’ 오매칭 방지),
    3글자 이상 복합어는 내부 공백 허용(‘가치 평가’→‘가치평가’)."""
    s = re.sub(r"\s+", "", s or "")
    body = r"\s*".join(map(re.escape, s)) if len(s) >= 3 else re.escape(s)
    return re.compile(body)


KWP = [(k, _pat(k)) for k in CFG["keywords"]]
EXC = [_pat(x) for x in CFG["exclude_patterns"]]


# ---------------------------------------------------------------- API
def fetch(op, bgn, end, page=1):
    q = {"serviceKey": SERVICE_KEY, "type": "json", "pageNo": page,
         "numOfRows": 999, "inqryDiv": 1, "inqryBgnDt": bgn, "inqryEndDt": end}
    url = BASE + op + "?" + urllib.parse.urlencode(q)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                body = json.loads(r.read().decode("utf-8"))["response"]["body"]
            return body.get("items") or [], int(body.get("totalCount") or 0)
        except Exception as e:
            if attempt == 2:
                raise RuntimeError("API 실패 %s p%d: %s" % (op, page, e))
            time.sleep(5)


def fetch_all(op, bgn, end):
    out, page = [], 1
    while True:
        items, total = fetch(op, bgn, end, page)
        out += items
        if not items or len(out) >= total or page >= 40:
            return out
        page += 1


# ---------------------------------------------------------------- 날짜·표시
def pdt(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", s or "")
    return datetime(*map(int, m.groups())) if m else None


def due_of(n):
    """목록 정렬·만료 판단용 기한. 입찰마감 → 없으면 개찰일시 → 없으면 게시 후 14일."""
    d = pdt(n.get("close")) or pdt(n.get("open"))
    if d:
        return d
    p = pdt(n.get("posted")) or pdt(n.get("found"))
    return p + timedelta(days=14) if p else None


def is_active(n, now):
    if n.get("status") == "cancelled":
        return False
    d = due_of(n)
    return bool(d and d >= now)


def md(d):
    return "%d/%d(%s)" % (d.month, d.day, WD[d.weekday()])


def dday(d, now):
    k = (d.date() - now.date()).days
    return "오늘" if k == 0 else ("내일" if k == 1 else "D-%d" % k)


def won(v):
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


def short(s, k):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= k else s[:k - 1] + "…"


# ---------------------------------------------------------------- 상태
def load_json(path, default):
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return default


def to_notice(it, kw, lic, found):
    return {"no": it.get("bidNtceNo", ""), "ord": it.get("bidNtceOrd", "") or "000",
            "kind": it.get("ntceKindNm", ""), "biz": OPS[it["_biz"]],
            "title": re.sub(r"\s+", " ", it.get("bidNtceNm", "") or "").strip(),
            "org": it.get("ntceInsttNm", ""), "dem": it.get("dminsttNm", ""),
            "posted": it.get("bidNtceDt", ""), "close": it.get("bidClseDt", ""),
            "open": it.get("opengDt", ""), "method": it.get("cntrctCnclsMthdNm", ""),
            "budget": it.get("asignBdgtAmt", "") or it.get("presmptPrce", ""),
            "kw": kw, "lic": lic, "url": it.get("bidNtceDtlUrl", ""),
            "found": found, "changed": "", "status": "open"}


# ---------------------------------------------------------------- 카톡 문안
def line_item(n, now, k):
    d = due_of(n)
    tail = []
    if n.get("org"):
        tail.append(short(n["org"], 16))
    if won(n.get("budget")):
        tail.append(won(n["budget"]))
    if d:
        tail.append("%s %s %s" % ("마감" if n.get("close") else "개찰", md(d), dday(d, now)))
    return "%d. %s\n   %s" % (k, short(n["title"], 42), " · ".join(tail))


def footer(active, now):
    soon = sum(1 for n in active if (due_of(n).date() - now.date()).days <= 1)
    return "진행 중 %d건 · 오늘·내일 마감 %d건" % (len(active), soon)


def msg_new(new, cancelled, active, now, limit=15):
    out = ["[나라장터] 신규 %d건 · %s %d시" % (len(new), md(now), now.hour)] if new \
        else ["[나라장터] 공고 취소 · %s %d시" % (md(now), now.hour)]
    for k, n in enumerate(new[:limit], 1):
        out.append(line_item(n, now, k))
    if len(new) > limit:
        out.append("…외 %d건은 전체 현황에서" % (len(new) - limit))
    for n in cancelled:
        out.append("✕ 취소: %s" % short(n["title"], 40))
    out += ["", footer(active, now)]
    return "\n".join(out)


def msg_digest(active, fresh, cancelled, now):
    out = ["[나라장터] %s %s" % (md(now), "아침 현황" if now.hour < 12 else "%d시 현황" % now.hour),
           "진행 중 %d건 · 지난 현황 이후 신규 %d건" % (len(active), len(fresh))]
    for label, k in (("오늘 마감", 0), ("내일 마감", 1)):
        xs = [n for n in active if (due_of(n).date() - now.date()).days == k]
        if xs:
            out += ["", "■ %s %d건" % (label, len(xs))]
            out += ["· %s %s (%s)" % (due_of(n).strftime("%H:%M"), short(n["title"], 34),
                                      short(n["org"], 12)) for n in xs]
    if fresh:
        out += ["", "■ 신규 %d건" % len(fresh)]
        out += [line_item(n, now, k) for k, n in enumerate(fresh[:15], 1)]
        if len(fresh) > 15:
            out.append("…외 %d건은 전체 현황에서" % (len(fresh) - 15))
    for n in cancelled:
        out.append("✕ 취소: %s" % short(n["title"], 40))
    return "\n".join(out)


# ---------------------------------------------------------------- main
def main():
    args   = sys.argv[1:]
    dry    = "--dry" in args
    notify = "--notify" in args and not dry
    if notify and not os.environ.get("KAKAO_REST_KEY"):
        print("[warn] 카카오 시크릿 미설정 — 발송 없이 스캔·페이지만 갱신", file=sys.stderr)
        notify = False
    force_digest = "--digest" in args
    hours  = float(args[args.index("--hours") + 1]) if "--hours" in args else None

    if not SERVICE_KEY:
        print(json.dumps({"error": "G2B_SERVICE_KEY 미설정"}, ensure_ascii=False))
        sys.exit(1)

    st   = load_json(STATE_F, {})
    db   = load_json(NOTICES_F, {})
    seen = set(st.get("seen", []))
    now  = now_kst()
    stamp = now.strftime("%Y-%m-%d %H:%M")

    if hours is not None:
        bgn_dt = now - timedelta(hours=hours)
    elif st.get("last_run"):
        bgn_dt = datetime.fromisoformat(st["last_run"]) - timedelta(minutes=CFG["lookback_overlap_minutes"])
        bgn_dt = max(bgn_dt, now - timedelta(hours=CFG["max_lookback_hours"]))
    else:
        bgn_dt = now - timedelta(hours=12)
    bgn, end = bgn_dt.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d%H%M")

    # 1) 면허(업종)제한 -> 공고번호별 면허명
    lic = {}
    for it in fetch_all("getBidPblancListInfoLicenseLimit", bgn, end):
        lic.setdefault(it.get("bidNtceNo", ""), set()).add(it.get("lcnsLmtNm", ""))

    # 2) 공고목록 — 같은 공고번호는 최신 차수(정정·취소)만 남긴다
    latest, scanned = {}, {}
    for suf in sorted(set(CFG["keyword_scope"]) | set(CFG["license_scope"])):
        items = fetch_all("getBidPblancListInfo" + suf, bgn, end)
        scanned[OPS[suf]] = len(items)
        for it in items:
            it["_biz"] = suf
            no = it.get("bidNtceNo", "")
            if no not in latest or (it.get("bidNtceOrd") or "") >= (latest[no].get("bidNtceOrd") or ""):
                latest[no] = it

    # 3) 매칭 + DB 반영
    new, cancelled, changed = [], [], []
    for no, it in latest.items():
        suf  = it["_biz"]
        kind = it.get("ntceKindNm", "")
        old  = db.get(no)

        if old:   # 이미 추적 중인 공고: 정정·취소만 반영
            if (it.get("bidNtceOrd") or "") > old.get("ord", ""):
                was_active = is_active(old, now)
                upd = to_notice(it, old["kw"], old["lic"], old["found"])
                if kind == "취소공고":
                    upd["status"] = "cancelled"
                    if was_active:
                        cancelled.append(upd)
                elif upd["close"] != old.get("close") or upd["open"] != old.get("open"):
                    upd["changed"] = stamp
                    changed.append(upd)
                else:
                    upd["changed"] = old.get("changed", "")
                db[no] = upd
            continue

        title = re.sub(r"\s+", " ", it.get("bidNtceNm", "") or "")
        kw_hit, lic_hit = [], []
        if suf in CFG["keyword_scope"]:
            t = title
            for ex in EXC:
                t = ex.sub(" ", t)          # 제외어는 공백으로 치환(붙여쓰기 재생성 방지)
            kw_hit = [k for k, pt in KWP if pt.search(t)]
        if suf in CFG["license_scope"]:
            lic_hit = sorted({nm for nm in lic.get(no, ()) if any(k in nm for k in CFG["license_keywords"])})
        if not (kw_hit or lic_hit) or kind == "취소공고":
            continue

        n = to_notice(it, kw_hit, lic_hit, stamp)
        db[no] = n
        if no not in seen:
            new.append(n)

    new.sort(key=lambda n: n["posted"], reverse=True)

    # 4) 오래된 공고 정리(기한 30일 경과) — seen에는 남아 재알림되지 않는다
    for no in [k for k, n in db.items() if (due_of(n) or now) < now - timedelta(days=30)]:
        del db[no]

    active = sorted((n for n in db.values() if is_active(n, now)), key=due_of)

    # 5) 카톡 — 아침 첫 실행이면 현황, 아니면 신규(이전 발송 실패분 포함)
    pending = [db[no] for no in st.get("pending", []) if no in db and is_active(db[no], now)]
    to_send = pending + [n for n in new if n["no"] not in st.get("pending", [])]
    today = now.strftime("%Y-%m-%d")
    want_digest = force_digest or (now.hour >= CFG.get("digest_hour", 8) and st.get("last_digest") != today)

    message = ""
    if want_digest:
        since = st.get("last_digest_at") or (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
        fresh = sorted((n for n in active if n["found"] >= since), key=lambda n: n["posted"], reverse=True)
        message = msg_digest(active, fresh, cancelled, now)
    elif to_send or cancelled:
        message = msg_new(to_send, cancelled, active, now)

    sent = None
    if message and notify:
        try:
            import kakao_notify
            kakao_notify.send(message, CFG.get("pages_url") or (to_send[0]["url"] if to_send else ""))
            sent = "ok"
        except Exception as e:
            sent = "ERROR: %s" % e
            print("[error] kakao: %s" % e, file=sys.stderr)

    # 6) 기록
    if not dry:
        if new:
            fresh_file = not os.path.exists(HIST_F)
            with open(HIST_F, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if fresh_file:
                    w.writerow(["탐지일시", "업무", "공고번호", "공고명", "공고기관", "수요기관",
                                "게시일시", "입찰마감", "개찰일시", "계약방법", "배정예산",
                                "매칭키워드", "매칭면허", "공고URL"])
                for n in new:
                    w.writerow([n["found"], n["biz"], n["no"], n["title"], n["org"], n["dem"],
                                n["posted"], n["close"], n["open"], n["method"], n["budget"],
                                ",".join(n["kw"]), " / ".join(n["lic"]), n["url"]])

        st["last_run"] = now.isoformat(timespec="seconds")
        st["seen"] = (st.get("seen", []) + [n["no"] for n in new])[-20000:]
        delivered = (sent == "ok")
        if notify:
            st["pending"] = [] if delivered else [n["no"] for n in to_send]
            if want_digest and delivered:
                st["last_digest"], st["last_digest_at"] = today, stamp
        json.dump(st, open(STATE_F, "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(db, open(NOTICES_F, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    try:
        import make_html
        make_html.render(active, now, scanned, (bgn_dt, now))
    except Exception as e:
        print("[warn] html: %s" % e, file=sys.stderr)

    print(json.dumps({"new": len(new), "pending": len(pending), "cancelled": len(cancelled),
                      "changed": len(changed), "active": len(active), "scanned": scanned,
                      "window": [bgn, end], "digest": want_digest, "kakao": sent},
                     ensure_ascii=False))
    if message:
        print("\n" + message)
    if sent and sent != "ok":
        sys.exit(2)     # 워크플로를 실패로 표시해 GitHub 메일 알림을 받는다(상태는 위에서 이미 저장)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        # 조달청 API 일시 장애: 상태를 건드리지 않았으므로 다음 실행이 같은 구간부터 다시 본다.
        # 6시간 넘게 이어질 때만 실패로 표시해 GitHub 메일이 오게 한다.
        print("[error] %s" % e, file=sys.stderr)
        last = load_json(STATE_F, {}).get("last_run")
        if not last or now_kst() - datetime.fromisoformat(last) > timedelta(hours=6):
            sys.exit(1)
