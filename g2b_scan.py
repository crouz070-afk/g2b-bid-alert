# -*- coding: utf-8 -*-
"""나라장터 공고 알림 (조달청 공공데이터포털 입찰공고정보서비스)

목표는 "남보다 먼저 입찰" — 평일 업무시간엔 5분마다 돌아 새 공고를 공고별 카톡으로 바로 보낸다.
매칭 공고는 notices.json에 누적하고, docs/index.html(전체 현황, 최신 공고순)을 만든다.
  - 신규 공고: 1건당 카톡 1통 + [공고 바로가기] 버튼(나라장터 공고로 직결)
  - 매일 아침(digest_hour) 첫 실행: 지난 아침 이후 신규 목록 1통

호출 절약(개발계정 하루 1,000회): 공고목록은 키워드 대상인 용역·기타만 받고,
물품·공사는 면허제한 목록에서 걸린 공고만 공고번호로 조회한다(실행당 약 3회).

GitHub Actions / 로컬 공용. 시각은 항상 KST 기준으로 계산한다.

사용법:
  python g2b_scan.py                  # 직전 실행 이후 스캔, 상태·페이지 갱신(발송 없음)
  python g2b_scan.py --notify         # 위 + 카카오톡 발송
  python g2b_scan.py --hours 24 --dry # 상태·발송 없이 테스트(결과만 출력)
  python g2b_scan.py --digest         # 아침 현황을 지금 만든다(--notify와 함께면 발송)

환경변수:
  G2B_SERVICE_KEY       공공데이터포털 서비스키(필수, config.json 값보다 우선)
  KAKAO_*               kakao_notify.py 참고 (--notify 시 필수)
  GITHUB_OUTPUT         Actions가 주입. 페이지를 다시 배포할지(deploy=true) 기록
"""
import urllib.request, urllib.parse, json, os, sys, csv, re, time, hashlib
from datetime import datetime, timedelta, timezone

BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/"
DIR  = os.path.dirname(os.path.abspath(__file__))
CFG  = json.load(open(os.path.join(DIR, "config.json"), encoding="utf-8"))
STATE_F   = os.path.join(DIR, "state.json")
NOTICES_F = os.path.join(DIR, "notices.json")
HIST_F    = os.path.join(DIR, "history.csv")

OPS  = {"Servc": "용역", "Thng": "물품", "Cnstwk": "공사", "Etc": "기타"}
SUF  = {v: k for k, v in OPS.items()}
KST  = timezone(timedelta(hours=9))
WD   = "월화수목금토일"
MAX_EACH = 5          # 한 번에 공고별로 보내는 최대 건수(넘치면 요약 1통)

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
def fetch(op, page=1, **params):
    q = {"serviceKey": SERVICE_KEY, "type": "json", "pageNo": page, "numOfRows": 999}
    q.update(params)
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


def fetch_window(op, bgn, end):
    out, page = [], 1
    while True:
        items, total = fetch(op, page, inqryDiv=1, inqryBgnDt=bgn, inqryEndDt=end)
        out += items
        if not items or len(out) >= total or page >= 40:
            return out
        page += 1


def fetch_by_no(suf, no):
    """공고번호로 전 차수를 받아 최신 차수 1건을 돌려준다."""
    items, _ = fetch("getBidPblancListInfo" + suf, inqryDiv=2, bidNtceNo=no)
    return max(items, key=lambda x: x.get("bidNtceOrd") or "") if items else None


# ---------------------------------------------------------------- 날짜·표시
def pdt(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", s or "")
    return datetime(*map(int, m.groups())) if m else None


def due_of(n):
    """만료 판단용 기한. 입찰마감 → 없으면 개찰일시 → 없으면 게시 후 14일."""
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


def to_notice(it, suf, kw, lic, found):
    return {"no": it.get("bidNtceNo", ""), "ord": it.get("bidNtceOrd", "") or "000",
            "kind": it.get("ntceKindNm", ""), "biz": OPS[suf],
            "title": re.sub(r"\s+", " ", it.get("bidNtceNm", "") or "").strip(),
            "org": it.get("ntceInsttNm", ""), "dem": it.get("dminsttNm", ""),
            "posted": it.get("bidNtceDt", ""), "close": it.get("bidClseDt", ""),
            "open": it.get("opengDt", ""), "method": it.get("cntrctCnclsMthdNm", ""),
            "budget": it.get("asignBdgtAmt", "") or it.get("presmptPrce", ""),
            "kw": kw, "lic": lic, "url": it.get("bidNtceDtlUrl", ""),
            "found": found, "changed": "", "status": "open"}


# ---------------------------------------------------------------- 카톡 문안
def msg_one(n):
    """공고 1건 = 카톡 1통. 바로 입찰 판단에 필요한 것만, 버튼은 나라장터 공고 직결."""
    p = pdt(n.get("posted"))
    org = n["org"] + (" → " + n["dem"] if n.get("dem") and n["dem"] != n["org"] else "")
    meta = " · ".join(x for x in (n["biz"], n.get("method"), won(n.get("budget"))) if x)
    match = " · ".join(n["kw"] + [x.split("/")[0] for x in n["lic"]])
    lines = ["[나라장터 신규]", n["title"], org, meta,
             "공고번호 %s-%s" % (n["no"], n.get("ord", "000"))]
    if p:
        lines.append("게시 %s %s" % (md(p), p.strftime("%H:%M")))
    if match:
        lines.append("매칭 " + match)
    return "\n".join(lines)


def msg_many(new, now):
    out = ["[나라장터 신규] %d건 · %s %s" % (len(new), md(now), now.strftime("%H:%M"))]
    for k, n in enumerate(new[:20], 1):
        out.append("%d. %s\n   %s · %s" % (k, short(n["title"], 42), short(n["org"], 16), n["no"]))
    if len(new) > 20:
        out.append("…외 %d건은 전체 현황에서" % (len(new) - 20))
    return "\n".join(out)


def msg_cancel(cancelled):
    return "\n".join(["[나라장터] 공고 취소 %d건" % len(cancelled)] +
                     ["✕ %s (%s)" % (short(n["title"], 40), n["no"]) for n in cancelled])


def msg_digest(active, fresh, now):
    out = ["[나라장터] %s %s" % (md(now), "아침 현황" if now.hour < 12 else "%d시 현황" % now.hour),
           "진행 중 %d건 · 지난 현황 이후 신규 %d건" % (len(active), len(fresh))]
    for k, n in enumerate(fresh[:20], 1):
        p = pdt(n.get("posted"))
        out.append("%d. %s\n   %s · %s 게시" % (k, short(n["title"], 42), short(n["org"], 16),
                                               "%s %s" % (md(p), p.strftime("%H:%M")) if p else "-"))
    if len(fresh) > 20:
        out.append("…외 %d건은 전체 현황에서" % (len(fresh) - 20))
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
    st0, db0 = json.dumps(st, sort_keys=True), json.dumps(db, sort_keys=True)
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

    # 1) 면허(업종)제한 -> 공고번호별 면허명·업무구분·차수
    lic, lic_biz, lic_ord = {}, {}, {}
    for it in fetch_window("getBidPblancListInfoLicenseLimit", bgn, end):
        no = it.get("bidNtceNo", "")
        lic.setdefault(no, set()).add(it.get("lcnsLmtNm", ""))
        lic_biz[no] = it.get("bsnsDivNm", "")
        lic_ord[no] = max(lic_ord.get(no, ""), it.get("bidNtceOrd") or "")

    # 2) 공고목록 — 키워드 대상(용역·기타)만 받는다. 같은 공고번호는 최신 차수만 남긴다
    latest, scanned = {}, {}
    for suf in CFG["keyword_scope"]:
        items = fetch_window("getBidPblancListInfo" + suf, bgn, end)
        scanned[OPS[suf]] = len(items)
        for it in items:
            it["_biz"] = suf
            no = it.get("bidNtceNo", "")
            if no not in latest or (it.get("bidNtceOrd") or "") >= (latest[no].get("bidNtceOrd") or ""):
                latest[no] = it

    # 2b) 그 밖의 업무(물품·공사)는 면허가 걸렸거나 추적 중 공고의 새 차수가 보일 때만 번호로 조회
    lookups = 0
    for no, names in lic.items():
        if no in latest:
            continue
        suf = SUF.get(lic_biz.get(no, ""))
        if not suf or suf not in CFG["license_scope"]:
            continue
        hit = any(k in nm for nm in names for k in CFG["license_keywords"])
        newer = no in db and lic_ord.get(no, "") > db[no].get("ord", "")
        if (hit and no not in db) or newer:
            it = fetch_by_no(suf, no)
            lookups += 1
            if it:
                it["_biz"] = suf
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
                upd = to_notice(it, suf, old["kw"], old["lic"], old["found"])
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

        n = to_notice(it, suf, kw_hit, lic_hit, stamp)
        db[no] = n
        if no not in seen:
            new.append(n)

    new.sort(key=lambda n: n["posted"])          # 카톡은 게시 순서대로 쌓이게

    # 4) 오래된 공고 정리(기한 30일 경과) — seen에는 남아 재알림되지 않는다
    for no in [k for k, n in db.items() if (due_of(n) or now) < now - timedelta(days=30)]:
        del db[no]

    active = [n for n in db.values() if is_active(n, now)]

    # 5) 카톡 — 신규는 공고별 즉시, 아침 첫 실행엔 현황 1통 추가
    pend_nos = st.get("pending", [])
    pending  = [db[no] for no in pend_nos if no in db and is_active(db[no], now)]
    to_send  = pending + [n for n in new if n["no"] not in pend_nos]
    today    = now.strftime("%Y-%m-%d")
    want_digest = force_digest or (CFG.get("digest_hour") is not None and now.hour >= CFG["digest_hour"]
                                   and st.get("last_digest") != today)

    msgs = []     # (문안, 링크, 대상 공고번호들)
    if len(to_send) > MAX_EACH:
        msgs.append((msg_many(to_send, now), CFG.get("pages_url", ""), [n["no"] for n in to_send]))
    else:
        msgs += [(msg_one(n), n["url"], [n["no"]]) for n in to_send]
    if cancelled:
        msgs.append((msg_cancel(cancelled), CFG.get("pages_url", ""), []))
    if want_digest:
        since = st.get("last_digest_at") or (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
        fresh = sorted((n for n in active if n["found"] >= since), key=lambda n: n["posted"], reverse=True)
        msgs.append((msg_digest(active, fresh, now), CFG.get("pages_url", ""), ["__digest__"]))

    sent, failed = 0, []
    if notify and msgs:
        import kakao_notify
        for text, link, nos in msgs:
            try:
                kakao_notify.send(text, link, "공고 바로가기" if link and link != CFG.get("pages_url") else "전체 현황")
                sent += 1
            except Exception as e:
                failed += nos
                print("[error] kakao: %s" % e, file=sys.stderr)

    # 6) 기록 — 바뀐 게 없으면 파일을 건드리지 않아 커밋도 생기지 않는다(마지막 실행시각은 2시간마다만 갱신)
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

        st["seen"] = (st.get("seen", []) + [n["no"] for n in new])[-20000:]
        if notify:
            st["pending"] = [no for no in failed if no != "__digest__"]
            if want_digest and "__digest__" not in failed:
                st["last_digest"], st["last_digest_at"] = today, stamp

    # 7) 전체 현황 페이지 — 내용이 바뀌었거나 1시간 지났을 때만 다시 배포
    import make_html
    page_hash = make_html.digest(active)
    deploy = (page_hash != st.get("page_hash")
              or not st.get("page_at") or now - datetime.fromisoformat(st["page_at"]) >= timedelta(minutes=60))
    if deploy:
        make_html.render(active, now)
        if not dry:
            st["page_hash"], st["page_at"] = page_hash, now.isoformat(timespec="seconds")
    if os.environ.get("GITHUB_OUTPUT"):
        open(os.environ["GITHUB_OUTPUT"], "a").write("deploy=%s\n" % str(deploy).lower())

    if not dry:
        stale = not st.get("last_run") or now - datetime.fromisoformat(st["last_run"]) >= timedelta(hours=2)
        dirty = json.dumps(db, sort_keys=True) != db0 or \
            json.dumps({k: v for k, v in st.items() if k != "last_run"}, sort_keys=True) != \
            json.dumps({k: v for k, v in json.loads(st0).items() if k != "last_run"}, sort_keys=True)
        if dirty or stale:
            st["last_run"] = now.isoformat(timespec="seconds")
            json.dump(st, open(STATE_F, "w", encoding="utf-8"), ensure_ascii=False)
            json.dump(db, open(NOTICES_F, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    print(json.dumps({"new": len(new), "pending": len(pending), "cancelled": len(cancelled),
                      "changed": len(changed), "active": len(active), "scanned": scanned,
                      "lookups": lookups, "window": [bgn, end], "digest": want_digest,
                      "kakao": "%d/%d" % (sent, len(msgs)) if notify else None, "deploy": deploy},
                     ensure_ascii=False))
    for text, _, _ in msgs:
        print("\n" + text)
    if failed:
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
