# -*- coding: utf-8 -*-
"""last_hits.json -> 표 이미지(PNG). 사용: python make_table.py [출력경로]

한글 폰트는 Windows(맑은 고딕)와 Ubuntu 러너(나눔고딕) 양쪽을 찾는다.
"""
import json, os, sys, re
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFont

DIR  = os.path.dirname(os.path.abspath(__file__))
HITS = os.path.join(DIR, "last_hits.json")
KST  = timezone(timedelta(hours=9))

W        = 1240
PAD      = 28
COLS     = [("공고명", 600), ("공고기관", 350), ("입찰시작", 234)]
ROW_PAD  = 13
LINE_H   = 26
HDR_H    = 46
FG       = (25, 32, 44)
MUTED    = (108, 118, 132)
HDR_BG   = (31, 45, 61)
HDR_FG   = (255, 255, 255)
ALT_BG   = (246, 248, 251)
LINE     = (222, 227, 234)
ACCENT   = (11, 92, 168)

FONTS_BOLD = [r"C:\Windows\Fonts\malgunbd.ttf",
              "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
              "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]
FONTS_REG  = [r"C:\Windows\Fonts\malgun.ttf",
              "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]


def font(sz, bold=False):
    for p in (FONTS_BOLD if bold else []) + FONTS_REG:
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


F_TITLE, F_SUB, F_HDR, F_BODY, F_SMALL = font(26, True), font(14), font(15, True), font(16), font(14)


def wrap(draw, text, fnt, maxw):
    """글자 단위 줄바꿈(한글은 공백이 적어 단어 단위로는 안 맞음)."""
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=fnt) <= maxw:
            cur += ch
        else:
            lines.append(cur); cur = ch
    if cur:
        lines.append(cur)
    return lines[:2] if len(lines) <= 2 else lines[:2][:-1] + [lines[1][:-1] + "…"]


def fmt_dt(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", s or "")
    if not m:
        return s or "-"
    y, mo, d, h, mi = m.groups()
    wd = "월화수목금토일"[datetime(int(y), int(mo), int(d)).weekday()]
    return "%s.%s(%s) %s:%s" % (mo, d, wd, h, mi)


def build(hits, out):
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    rows = []
    for h in hits:
        nm  = wrap(tmp, h.get("공고명", ""), F_BODY, COLS[0][1] - 24)
        ins = wrap(tmp, h.get("공고기관", ""), F_BODY, COLS[1][1] - 24)
        rows.append((nm, ins, fmt_dt(h.get("입찰시작", "")), h))

    top = PAD + 40 + 26 + 18
    hs  = [max(len(r[0]), len(r[1])) * LINE_H + ROW_PAD * 2 for r in rows]
    H   = top + HDR_H + sum(hs) + PAD + 26

    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    d.text((PAD, PAD), "나라장터 신규 공고", font=F_TITLE, fill=FG)
    d.text((PAD, PAD + 36), "%s  ·  %d건  ·  회계·감사·세무·원가·자문 / 회계법인·원가검토기관 면허"
           % (now, len(rows)), font=F_SUB, fill=MUTED)

    y = top
    x = PAD
    d.rectangle([PAD, y, W - PAD, y + HDR_H], fill=HDR_BG)
    for name, cw in COLS:
        d.text((x + 12, y + 14), name, font=F_HDR, fill=HDR_FG)
        x += cw
    y += HDR_H

    for i, (nm, ins, bd, h) in enumerate(rows):
        rh = hs[i]
        if i % 2:
            d.rectangle([PAD, y, W - PAD, y + rh], fill=ALT_BG)
        d.line([PAD, y + rh, W - PAD, y + rh], fill=LINE)
        x = PAD
        for j, (lines, cw) in enumerate(((nm, COLS[0][1]), (ins, COLS[1][1]))):
            ty = y + ROW_PAD
            for ln in lines:
                d.text((x + 12, ty), ln, font=F_BODY, fill=FG if j == 0 else MUTED)
                ty += LINE_H
            x += cw
        d.text((x + 12, y + ROW_PAD), bd, font=F_BODY, fill=ACCENT)
        if h.get("면허"):
            d.text((x + 12, y + ROW_PAD + LINE_H), h["면허"][0].split("/")[0], font=F_SMALL, fill=MUTED)
        y += rh

    d.text((PAD, y + 12), "GitHub Actions 자동 스캔 · 매일 08:00 / 18:00 KST", font=F_SMALL, fill=MUTED)
    img.save(out)
    return out


def main():
    hits = json.load(open(HITS, encoding="utf-8")) if os.path.exists(HITS) else []
    if not hits:
        print("no hits"); return
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        DIR, "out", "notices_%s.png" % datetime.now(KST).strftime("%Y%m%d_%H%M"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    print(build(hits, out))


if __name__ == "__main__":
    main()
