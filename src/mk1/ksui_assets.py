#!/usr/bin/env python3
"""KEY SHIFT pad artwork for the MK1 PERFORM hot-cue row (RGB565, for ksui.c).

Source: a stock PERFORM screenshot (model table ksui_layout.source; the deck
draws the row from firmware sprites, the screenshot is their rendering).
Per pad: the stock pixels, with the band behind the stock text rebuilt from
the pad's own texture (every row repeats with a period <= 4 px, as on the
BEAT JUMP pads, see bjlabels.py) and our text drawn in the stock ink.
Fonts: Helvetica Neue Bold sized to the stock cap heights (pad letters 14 px,
REC/CALL 11 px, row label 8 px). Upstream's PERFORM pads use the same family.

Images (in this order, packed into ksui_img.bin; offsets in ksui_layout.h):
  A "-"  C "+"  REC "RESET"  CALL "BACK"   (pads keep their stock size)
  B: "-6".."+6" (13), "MT OFF", "N/A" (key shift engine not installed)
  TITLE: "KEY SHIFT" over the row label (stock label colour)

    ksui_assets.py build     -> work/ksui/build/ksui_img.bin, ksui_layout.h, preview.png
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
E_ = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
L = E_["ksui_layout"]
OUT = os.path.join(ROOT, "work", "ksui", "build")
FONT = "/System/Library/Fonts/HelveticaNeue.ttc"
MINUS = "−"


def to565(a):
    """screenshot RGB888 (expanded v*255//max) -> exact RGB565 levels"""
    a = a.astype(np.int32)
    return np.dstack([(a[..., 0] * 31 + 127) // 255, (a[..., 1] * 63 + 127) // 255, (a[..., 2] * 31 + 127) // 255])


def pack(a):
    a = np.clip(a, 0, [31, 63, 31])
    return ((a[..., 0] << 11) | (a[..., 1] << 5) | a[..., 2]).astype("<u2").tobytes()


def rgb8(a):
    a = np.clip(a, 0, [31, 63, 31])
    return np.dstack([a[..., 0] * 255 // 31, a[..., 1] * 255 // 63, a[..., 2] * 255 // 31]).astype(np.uint8)


def rebuild(pad, rows, text_cols):
    """rows of `pad` rebuilt from the columns outside text_cols, by x mod p"""
    out = pad.copy()
    W = pad.shape[1]
    known = [x for x in range(4, W - 4) if not text_cols[0] <= x < text_cols[1]]
    for y in rows:
        for p in (1, 2, 4, 8):
            val = {}
            if all(val.setdefault(x % p, tuple(pad[y, x])) == tuple(pad[y, x]) for x in known):
                for x in range(4, W - 4):
                    out[y, x] = val[x % p]
                break
        else:
            raise SystemExit("ksui_assets: pad row %d has no texture period" % y)
    return out


def font_for(cap):
    """Helvetica Neue Bold whose 'H' is `cap` px tall at 4x supersampling"""
    for size in range(8, 40):
        f = ImageFont.truetype(FONT, size * 4, index=1)
        b = f.getbbox("H")
        if (b[3] - b[1]) / 4 >= cap - 0.25:
            return f
    raise SystemExit("no font size")


def alpha(text, font, w, h, cx, base):
    """anti-aliased alpha (0..1) of `text`, centred on cx, baseline at `base`"""
    im = Image.new("L", (w * 4, h * 4), 0)
    d = ImageDraw.Draw(im)
    d.text((cx * 4, base * 4), text, font=font, fill=255, anchor="ms")
    return np.asarray(im.resize((w, h), Image.LANCZOS)).astype(np.float64) / 255.0


def compose(bg, a, ink):
    return np.rint(bg + a[..., None] * (np.array(ink, float) - bg)).astype(np.int32)


def build():
    src = os.path.join(ROOT, L["source"])
    scr = to565(np.asarray(Image.open(src).convert("RGB")))
    y0, y1 = L["row_y"]
    H = y1 - y0 + 1
    pads = {k: tuple(v) for k, v in L["pads"].items()}          # name -> (x0, x1)
    band = range(L["text_band"][0] - y0, L["text_band"][1] - y0 + 1)
    ink = to565(np.array([[L["pad_ink"]]]))[0, 0].astype(float)
    big, small = font_for(L["cap_big"]), font_for(L["cap_small"])
    sym = font_for(L["cap_big"] + 6)                  # - and + read small at letter size
    base_big = L["baseline_big"] - y0
    base_small = L["baseline_small"] - y0
    imgs, lay = [], []

    def pad_img(name, text, font, base):
        x0, x1 = pads[name]
        w = x1 - x0 + 1
        p = scr[y0:y1 + 1, x0:x1 + 1].astype(np.int32)
        bg = rebuild(p, band, (w // 5, w - w // 5))
        a = alpha(text, font, w, H, w / 2, base)
        a[:band.start] = 0
        a[band.stop:] = 0
        return compose(bg.astype(float), a, ink), w

    def add(tag, img, w, h):
        imgs.append((tag, img))
        lay.append((tag, w, h))

    for name, text, f, b in (("A", MINUS, sym, base_big + 3), ("C", "+", sym, base_big + 3),
                             ("REC", "RESET", small, base_small), ("CALL", "BACK", small, base_small)):
        img, w = pad_img(name, text, f, b)
        add(name, img, w, H)
    for s in range(-6, 7):
        t = "0" if s == 0 else ("+%d" % s if s > 0 else MINUS + "%d" % -s)
        img, w = pad_img("B", t, big, base_big)
        add("B%+d" % s, img, w, H)
    for tag, t in (("BMT", "MT OFF"), ("BNA", "N/A")):
        img, w = pad_img("B", t, small, base_small)
        add(tag, img, w, H)
    # title over the row label: black background, stock label colour
    tx0, tx1 = L["title_x"]
    ty0, ty1 = L["title_y"]
    tw, th = tx1 - tx0 + 1, ty1 - ty0 + 1
    bgt = scr[ty0:ty1 + 1, tx0:tx1 + 1].astype(float) * 0           # label area is plain black
    a = alpha("KEY SHIFT", font_for(L["cap_label"]), tw, th, tw / 2, L["baseline_label"] - ty0)
    lab = to565(np.array([[L["label_ink"]]]))[0, 0].astype(float)
    add("TITLE", compose(bgt, a, lab), tw, th)

    os.makedirs(OUT, exist_ok=True)
    blob, offs = bytearray(), {}
    for tag, img in imgs:
        offs[tag] = len(blob)
        blob += pack(img)
    open(os.path.join(OUT, "ksui_img.bin"), "wb").write(blob)
    with open(os.path.join(OUT, "ksui_layout.h"), "w") as f:
        f.write("/* generated by mk1/ksui_assets.py */\n")
        for tag, w, h in lay:
            n = "IMG_" + tag.replace("+", "P").replace("-", "M")
            f.write("#define %s_OFF %du\n#define %s_W %d\n#define %s_H %d\n" % (n, offs[tag], n, w, n, h))
    # preview: the row as it will look (B = +2), plus every B variant
    row = scr[y0:y1 + 1, :640].astype(np.int32).copy()
    d = dict(imgs)
    for name, tag in (("A", "A"), ("B", "B+2"), ("C", "C"), ("REC", "REC"), ("CALL", "CALL")):
        x0, x1 = pads[name]
        row[:, x0:x1 + 1] = d[tag]
    row[ty0 - y0:ty1 - y0 + 1, tx0:tx1 + 1] = d["TITLE"]
    vs = np.hstack([d["B%+d" % s] for s in (-6, -1, 0, 1, 6)] + [d["BMT"], d["BNA"]])
    pv = np.vstack([rgb8(row), np.zeros((6, 640, 3), np.uint8), rgb8(vs)[:, :640]])
    Image.fromarray(pv).resize((1280, pv.shape[0] * 2), Image.NEAREST).save(os.path.join(OUT, "preview.png"))
    import hashlib
    print("ksui_img.bin %d B (%d images), sha256 %s" % (len(blob), len(imgs), hashlib.sha256(blob).hexdigest()))
    return bytes(blob), offs


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        build()
    else:
        print(__doc__)
