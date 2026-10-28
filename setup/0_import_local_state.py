# -*- coding: utf-8 -*-
"""기존 로컬 알림(나라장터_공고알림 폴더)의 이력·상태를 이 리포지토리로 옮긴다.

실행:  python setup/0_import_local_state.py

- 공고이력.csv -> history.csv, notices.json(진행 중 공고 DB)
- state.json의 last_run·seen -> state.json (이미 알린 공고를 다시 알리지 않게)
GitHub으로 올리기 직전에 한 번 실행한다. 여러 번 실행해도 결과는 같다.
"""
import csv, json, os, shutil, sys, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD  = os.path.join(os.path.dirname(ROOT), "나라장터_공고알림")


def main():
    hist = os.path.join(OLD, "공고이력.csv")
    st_f = os.path.join(OLD, "state.json")
    if not (os.path.exists(hist) and os.path.exists(st_f)):
        raise SystemExit("기존 폴더를 찾지 못했습니다: %s" % OLD)

    shutil.copyfile(hist, os.path.join(ROOT, "history.csv"))

    db = {}
    for r in csv.DictReader(open(hist, encoding="utf-8-sig")):
        db[r["공고번호"]] = {
            "no": r["공고번호"], "ord": "000", "kind": "", "biz": r["업무"], "title": r["공고명"],
            "org": r["공고기관"], "dem": r["수요기관"], "posted": r["게시일시"], "close": r["입찰마감"],
            "open": r["개찰일시"], "method": r["계약방법"], "budget": r["배정예산"],
            "kw": [k for k in r["매칭키워드"].split(",") if k],
            "lic": [x for x in r["매칭면허"].split(" / ") if x],
            "url": r["공고URL"], "found": r["탐지일시"], "changed": "", "status": "open"}
        # 상세 URL의 차수로 ord를 맞춘다(이후 정정공고 비교 기준)
        if "bidPbancOrd=" in r["공고URL"]:
            db[r["공고번호"]]["ord"] = r["공고URL"].split("bidPbancOrd=")[1][:3]
    # 아직 기한 전인 공고는 공고번호로 다시 조회해 최신 차수(정정·취소)를 반영한다.
    # 기존 로컬 알림은 취소공고도 신규로 잡았으므로 여기서 걸러진다.
    sys.path.insert(0, ROOT)
    os.environ.setdefault("G2B_SERVICE_KEY",
                          json.load(open(os.path.join(OLD, "config.json"), encoding="utf-8"))["serviceKey"])
    import g2b_scan as g
    now, fixed = g.now_kst(), 0
    for no, n in db.items():
        if not g.is_active(n, now):
            continue
        suf = {v: k for k, v in g.OPS.items()}[n["biz"]]
        q = {"serviceKey": g.SERVICE_KEY, "type": "json", "pageNo": 1, "numOfRows": 50,
             "inqryDiv": 2, "bidNtceNo": no}
        url = g.BASE + "getBidPblancListInfo" + suf + "?" + urllib.parse.urlencode(q)
        items = json.loads(urllib.request.urlopen(url, timeout=60).read().decode("utf-8"))["response"]["body"].get("items") or []
        if not items:
            continue
        it = max(items, key=lambda x: x.get("bidNtceOrd") or "")
        it["_biz"] = suf
        upd = g.to_notice(it, n["kw"], n["lic"], n["found"])
        if it.get("ntceKindNm") == "취소공고":
            upd["status"] = "cancelled"
        if (upd["ord"], upd["status"], upd["close"]) != (n["ord"], n["status"], n["close"]):
            fixed += 1
        db[no] = upd
    print("진행 중 공고 재조회: 정정·취소 반영 %d건" % fixed)

    json.dump(db, open(os.path.join(ROOT, "notices.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    old = json.load(open(st_f, encoding="utf-8"))
    seen = list(dict.fromkeys(old.get("seen", []) + list(db)))
    st = {"last_run": old.get("last_run"), "seen": seen[-20000:], "pending": []}
    json.dump(st, open(os.path.join(ROOT, "state.json"), "w", encoding="utf-8"), ensure_ascii=False)

    print("이관 완료: 공고 %d건, 알림이력 %d건, 마지막 실행 %s" % (len(db), len(seen), st["last_run"]))


if __name__ == "__main__":
    main()
