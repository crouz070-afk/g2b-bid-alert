# -*- coding: utf-8 -*-
"""나라장터 신규 공고 스캐너 (조달청 공공데이터포털 입찰공고정보서비스)

GitHub Actions / 로컬 공용. 시각은 항상 KST 기준으로 계산한다.

사용법:
  python g2b_scan.py                  # 마지막 실행시각 이후 신규분, 상태 갱신
  python g2b_scan.py --notify         # 위 + 신규가 있으면 카카오톡 발송
  python g2b_scan.py --hours 24       # 최근 24시간 재스캔(상태 갱신)
  python g2b_scan.py --hours 24 --dry # 상태 갱신·발송 없이 테스트만

환경변수:
  G2B_SERVICE_KEY       공공데이터포털 서비스키(필수, config.json 값보다 우선)
  KAKAO_REST_KEY        카카오 REST API 키       (--notify 시 필수)
  KAKAO_REFRESH_TOKEN   카카오 리프레시 토큰      (--notify 시 필수)
"""
import urllib.request, urllib.parse, json, os, sys, csv, re, time
from datetime import datetime, timedelta, timezone

BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/"
DIR  = os.path.dirname(os.path.abspath(__file__))
CFG  = json.load(open(os.path.join(DIR, "config.json"), encoding="utf-8"))
STATE_F = os.path.join(DIR, "state.json")
HIST_F  = os.path.join(DIR, "history.csv")
SUMM_F  = os.path.join(DIR, "last_summary.txt")
OUT_DIR = os.path.join(DIR, "out")

KST = timezone(timedelta(hours=9))
OPS = {"Servc": "용역", "Thng": "물품", "Cnstwk": "공사", "Etc": "기타"}

SERVICE_KEY = os.environ.get("G2B_SERVICE_KEY") or CFG.get("serviceKey") or ""


def now_kst():
    """러너는 UTC이므로 항상 KST로 환산한다. 이후 포맷팅 호환을 위해 naive로 돌려준다."""
    return datetime.now(KST).replace(tzinfo=None)


def _pat(s):
    """2글자 키워드는 공백 불허(‘제16회 계룡’→‘회계’ 오매칭 방지),
    3글자 이상 복합어는 내부 공백 허용(‘가치 평가’→‘가치평가’)."""
    s = re.sub(r"\s+", "", s or "")
    body = r"\s*".join(map(re.escape, s)) if len(s) >= 3 else re.escape(s)
    return re.compile(body)


KWP = [(k, _pat(k)) for k in CFG["keywords"]]
EXC = [_pat(x) for x in CFG["exclude_patterns"]]


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
            time.sleep(3)


def fetch_all(op, bgn, end):
    out, page = [], 1
    while True:
        items, total = fetch(op, bgn, end, page)
        out += items
        if not items or len(out) >= total:
            return out
        page += 1
        if page > 40:
            return out


def load_state():
    if os.path.exists(STATE_F):
        return json.load(open(STATE_F, encoding="utf-8"))
    return {"last_run": None, "seen": []}


def build_summary(hits, now, link_url):
    """카카오 텍스트 템플릿용 200자 요약. 링크는 버튼으로 따로 붙으므로 본문에 넣지 않는다."""
    head = "[나라장터] %s 신규 %d건" % (now.strftime("%m/%d %H:%M"), len(hits))
    body, shown = "", 0
    for it in hits:
        nm = it.get("bidNtceNm", "")[:28]
        ln = "\n· %s(%s)" % (nm, it.get("ntceInsttNm", "")[:10])
        if len(head) + len(body) + len(ln) + 12 > 195:
            break
        body += ln
        shown += 1
    rest = "\n외 %d건" % (len(hits) - shown) if len(hits) > shown else ""
    return (head + body + rest)[:200]


def main():
    args   = sys.argv[1:]
    dry    = "--dry" in args
    notify = "--notify" in args and not dry
    hours  = None
    if "--hours" in args:
        hours = float(args[args.index("--hours") + 1])

    if not SERVICE_KEY:
        print(json.dumps({"error": "G2B_SERVICE_KEY 미설정"}, ensure_ascii=False))
        sys.exit(1)

    st   = load_state()
    seen = set(st.get("seen", []))
    now  = now_kst()

    if hours is not None:
        bgn_dt = now - timedelta(hours=hours)
    elif st.get("last_run"):
        bgn_dt = datetime.fromisoformat(st["last_run"]) - timedelta(minutes=CFG["lookback_overlap_minutes"])
        floor  = now - timedelta(hours=CFG["max_lookback_hours"])
        bgn_dt = max(bgn_dt, floor)
    else:
        bgn_dt = now - timedelta(hours=12)

    bgn, end = bgn_dt.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d%H%M")

    # 1) 면허(업종)제한 -> 공고번호별 면허명
    lic = {}
    for it in fetch_all("getBidPblancListInfoLicenseLimit", bgn, end):
        lic.setdefault(it.get("bidNtceNo", ""), set()).add(it.get("lcnsLmtNm", ""))

    # 2) 공고목록 수집
    notices, scanned = {}, {}
    for suf in sorted(set(CFG["keyword_scope"]) | set(CFG["license_scope"])):
        items = fetch_all("getBidPblancListInfo" + suf, bgn, end)
        scanned[OPS[suf]] = len(items)
        for it in items:
            it["_biz"] = suf
            notices[it.get("bidNtceNo", "")] = it

    # 3) 매칭
    hits = []
    for no, it in notices.items():
        suf   = it["_biz"]
        title = re.sub(r"\s+", " ", it.get("bidNtceNm", "") or "")
        kw_hit, lic_hit = [], []
        if suf in CFG["keyword_scope"]:
            t = title
            for ex in EXC:
                t = ex.sub(" ", t)          # 제외어는 공백으로 치환(붙여쓰기 재생성 방지)
            kw_hit = [k for k, pt in KWP if pt.search(t)]
        if suf in CFG["license_scope"]:
            for nm in lic.get(no, ()):
                if any(k in nm for k in CFG["license_keywords"]):
                    lic_hit.append(nm)
        if (kw_hit or lic_hit) and no not in seen:
            it["_kw"], it["_lic"] = kw_hit, sorted(set(lic_hit))
            hits.append(it)

    hits.sort(key=lambda x: x.get("bidNtceDt", ""), reverse=True)

    # 4) 이력 CSV 기록
    if hits and not dry:
        new = not os.path.exists(HIST_F)
        with open(HIST_F, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["탐지일시", "업무", "공고번호", "공고명", "공고기관", "수요기관",
                            "게시일시", "입찰마감", "개찰일시", "계약방법", "배정예산",
                            "매칭키워드", "매칭면허", "공고URL"])
            for it in hits:
                w.writerow([now.strftime("%Y-%m-%d %H:%M"), OPS[it["_biz"]],
                            it.get("bidNtceNo", ""), it.get("bidNtceNm", ""),
                            it.get("ntceInsttNm", ""), it.get("dminsttNm", ""),
                            it.get("bidNtceDt", ""), it.get("bidClseDt", ""),
                            it.get("opengDt", ""), it.get("cntrctCnclsMthdNm", ""),
                            it.get("asignBdgtAmt", "") or it.get("presmptPrce", ""),
                            ",".join(it["_kw"]), " / ".join(it["_lic"]),
                            it.get("bidNtceDtlUrl", "")])

    # 4b) 최근 결과 JSON(표·HTML 생성용) — dry 실행에서도 기록
    json.dump([{"공고명": it.get("bidNtceNm", ""), "공고기관": it.get("ntceInsttNm", ""),
                "수요기관": it.get("dminsttNm", ""), "입찰시작": it.get("bidBeginDt", "") or it.get("bidNtceDt", ""),
                "입찰마감": it.get("bidClseDt", ""), "예산": it.get("asignBdgtAmt", "") or it.get("presmptPrce", ""),
                "계약방법": it.get("cntrctCnclsMthdNm", ""), "업무": OPS[it["_biz"]],
                "공고번호": it.get("bidNtceNo", ""), "URL": it.get("bidNtceDtlUrl", ""),
                "키워드": it["_kw"], "면허": it["_lic"]} for it in hits],
              open(os.path.join(DIR, "last_hits.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    json.dump({"generated": now.isoformat(timespec="minutes"), "window": [bgn, end],
               "scanned": scanned, "count": len(hits)},
              open(os.path.join(DIR, "last_meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 4c) 공개용 HTML — 신규가 있을 때만 갱신한다.
    # 0건일 때 덮어쓰면, 직전 카톡 링크를 나중에 눌렀을 때 빈 페이지가 뜬다.
    if hits:
        try:
            import make_html
            make_html.render()
        except Exception as e:
            print("[warn] html: %s" % e, file=sys.stderr)

    # 5) 상세 리포트
    detail = ""
    if hits:
        lines = ["나라장터 신규 공고  %s" % now.strftime("%Y-%m-%d %H:%M"),
                 "조회구간 %s ~ %s" % (bgn_dt.strftime("%m/%d %H:%M"), now.strftime("%m/%d %H:%M")),
                 "스캔 %s / 신규매칭 %d건" % (", ".join("%s %d" % (k, v) for k, v in scanned.items()), len(hits)), ""]
        for i, it in enumerate(hits, 1):
            lines += ["[%d] %s" % (i, it.get("bidNtceNm", "")),
                      "    %s | %s | 마감 %s" % (OPS[it["_biz"]], it.get("ntceInsttNm", ""), it.get("bidClseDt", "")),
                      "    예산 %s | 계약 %s" % (it.get("asignBdgtAmt", "") or "-", it.get("cntrctCnclsMthdNm", "")),
                      "    매칭 %s%s" % (",".join(it["_kw"]) or "-",
                                        (" | 면허:" + " / ".join(it["_lic"])) if it["_lic"] else ""),
                      "    %s  %s" % (it.get("bidNtceNo", ""), it.get("bidNtceDtlUrl", "")), ""]
        detail = "\n".join(lines)
        if not dry:
            os.makedirs(OUT_DIR, exist_ok=True)
            open(os.path.join(OUT_DIR, "notices_%s.txt" % now.strftime("%Y%m%d_%H%M")),
                 "w", encoding="utf-8").write(detail)

    # 5b) 표 이미지(PNG) 생성 — 실패해도 알림은 계속되도록 격리
    png = ""
    if hits and not dry:
        try:
            import make_table
            os.makedirs(OUT_DIR, exist_ok=True)
            png = make_table.build(json.load(open(os.path.join(DIR, "last_hits.json"), encoding="utf-8")),
                                   os.path.join(OUT_DIR, "notices_%s.png" % now.strftime("%Y%m%d_%H%M")))
        except Exception as e:
            png = "ERROR: %s" % e

    # 6) 카톡 요약 + 발송
    link_url = CFG.get("pages_url") or (hits[0].get("bidNtceDtlUrl", "") if hits else "")
    summary  = build_summary(hits, now, link_url) if hits else ""
    sent     = None
    if hits and notify:
        try:
            import kakao_notify
            kakao_notify.send(summary, link_url)
            sent = "ok"
        except Exception as e:
            sent = "ERROR: %s" % e
            print("[error] kakao: %s" % e, file=sys.stderr)

    if not dry:
        st["last_run"] = now.isoformat(timespec="seconds")
        st["seen"] = (st.get("seen", []) + [h.get("bidNtceNo", "") for h in hits])[-20000:]
        json.dump(st, open(STATE_F, "w", encoding="utf-8"), ensure_ascii=False)
        open(SUMM_F, "w", encoding="utf-8").write(summary)

    print(json.dumps({"new_count": len(hits), "scanned": scanned,
                      "window": [bgn, end], "kakao_summary": summary,
                      "summary_len": len(summary), "kakao_sent": sent,
                      "link": link_url, "png": png}, ensure_ascii=False))
    if detail:
        print("\n" + detail)

    # 발송 실패는 워크플로를 붉게 만들어 알아차릴 수 있게 한다.
    if sent and sent != "ok":
        sys.exit(2)


if __name__ == "__main__":
    main()
