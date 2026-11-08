#!/usr/bin/env python3
"""BEAT JUMP pad labels 1..64 for MK1, rendered from the firmware's own digits.

Replaces padlabels.py's transplant (it left the old digit's edge pixels and
garbled the new one). Here, per style (normal / lit / dim):

  background  In the digit band the pad texture repeats every <= 4 px along
              each row, and is the same on every pad of both directions
              (only the border columns differ). Each row is rebuilt from the
              columns left and right of the digit box by x mod period.
  glyph       alpha per pixel = (pixel - bg) / (ink - bg) on the channel with
              the most contrast, from the normal style; 1, 2, 4 from the BEAT
              JUMP pads, 8 and 6 from the BEAT LOOP pads' 8 and 16 (same font
              and size, model table). Rendered in each style's own bg and ink.
  label       bg + alpha * (ink - bg), digits laid out with the gap of the
              BEAT LOOP "16", centred where that pad's stock digit is centred.

validate(): the stock 1/2/4 re-rendered from their own alpha onto the rebuilt
background must match the stock sprites (max channel difference reported).
"3" exists in no pad sprite; see glyph3().

    bjlabels.py check            validate + preview work/bjswipe/labels.png
    bjlabels.py build            work/bjswipe/build/labels.bin + labels.json
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import padlabels as PL                                          # noqa: E402

E_ = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
BJ, BL = E_["bj_pad_sprites"], E_["bl_pad_sprites"]
W = BJ["w"]
BOX_X = (26, 56)                       # digit box columns (rebuilt), both pad kinds
BL_BOX = (26, 51)                      # BEAT LOOP pads: a pad feature sits at x 52


def v16(a):
    return (a[..., 0] << 11) | (a[..., 1] << 5) | a[..., 2]


def rebuild_bg(sprites, rows, cols_ok):
    """Per row: the period p in (1, 2, 4) under which the known columns agree
    across all given sprites, then every column x <- known value at x mod p."""
    out = sprites[0].copy()
    bad = []
    for y in rows:
        for p in (1, 2, 4, 8):
            val = {}
            good = True
            for s in sprites:
                for x in cols_ok:
                    k = x % p
                    v = tuple(s[y, x])
                    if val.setdefault(k, v) != v:
                        good = False
                        break
                if not good:
                    break
            if good and len(val) == p:
                for x in range(W):
                    out[y, x] = val[x % p]
                break
        else:
            bad.append(y)
    return out, bad


class Labels:
    def __init__(self, img):
        self.P = PL.Pads(img)
        P = self.P
        y0 = BJ["digit_y0"]
        self.band = range(y0 - 5, y0 + 21)                    # 20..45
        cols = [x for x in range(4, 75) if not BOX_X[0] <= x < BOX_X[1]]
        self.bg, self.bad = {}, {}
        for k in range(3):
            fwd = [P.bjs[(l, "fwd")][k] for l in ("1", "2", "4")]
            self.bg[k], self.bad[k] = rebuild_bg(fwd, self.band, cols)
        ly0 = BL["digit_y0"]
        self.lband = range(ly0 - 5, ly0 + 21)
        self.lbg = {}
        for k in range(3):
            pads = [P.bls[l][k] for l in P.bls]
            self.lbg[k], bad = rebuild_bg(pads, self.lband, cols)
            self.bad["bl%d" % k] = bad
        self.ink = {k: self._ink(k) for k in range(3)}

    def _ink(self, k):
        """text colour of style k: the brightest pixel of the stock '1' (a solid stem)"""
        a = self.P.bjs[("1", "fwd")][k]
        ys = slice(BJ["digit_y0"], BJ["digit_y0"] + 16)
        g = a[ys, BOX_X[0]:BOX_X[1]]
        i = np.unravel_index(np.argmax(g[..., 1]), g.shape[:2])
        return g[i].astype(np.float64)

    def alpha(self, sprite, bg, k, rows, box=BOX_X):
        ink = self.ink[k]
        d = ink - bg.astype(np.float64)
        ch = np.argmax(np.abs(d), axis=2)
        num = np.take_along_axis(sprite - bg, ch[..., None], 2)[..., 0].astype(np.float64)
        den = np.take_along_axis(d, ch[..., None], 2)[..., 0]
        a = np.where(np.abs(den) > 0.5, num / np.where(den == 0, 1, den), 0.0)
        m = np.zeros_like(a)
        m[rows.start:rows.stop, box[0]:box[1]] = 1
        return np.clip(a, 0, 1) * m

    def glyphs(self, k):
        """{digit: alpha cropped to its ink columns, rows = the BEAT JUMP band offset}"""
        P, out = self.P, {}
        for l in ("1", "2", "4"):
            out[l] = self.alpha(P.bjs[(l, "fwd")][k], self.bg[k], k, self.band)
        dy = BJ["digit_y0"] - BL["digit_y0"]
        for l in ("8", "16"):
            a = self.alpha(P.bls[l][k], self.lbg[k], k, self.lband, BL_BOX)
            full = np.zeros((BJ["h"], W))
            full[dy:dy + BL["h"]] = a[:BJ["h"] - dy]
            out[l] = full
        # split 16 into 1 + 6 at the empty column between them
        a16 = out["16"]
        colsum = a16.sum(axis=0)
        ink = np.nonzero(colsum > 0.05)[0]
        gaps = [x for x in range(ink[0], ink[-1]) if colsum[x] <= 0.05]
        split = gaps[len(gaps) // 2]
        six = a16.copy()
        six[:, :split] = 0
        out["6"] = six
        one16 = a16.copy()
        one16[:, split:] = 0
        self.gap16 = _cols(six)[0] - _cols(one16)[1] - 1    # empty columns between 1 and 6
        out.pop("16")
        g3 = self.glyph3(k, out)
        if g3 is not None:
            out["3"] = g3
        return out

    def glyph3(self, k, g):
        """No pad sprite carries a 3. Built from the firmware 8: its right half
        (the closed bowls become the 3's open curves), the left side cleared
        except the top and bottom terminals. Marked synthetic in labels.json."""
        a8 = g["8"].copy()
        x0, x1 = _cols(a8)
        rows = np.nonzero(a8.sum(axis=1) > 0.05)[0]
        r0, r1 = rows[0], rows[-1]
        h = r1 - r0 + 1
        cut = x0 + (x1 - x0 + 1) * 45 // 100
        out = a8.copy()
        keep_top = r0 + max(2, h * 18 // 100)
        keep_bot = r1 - max(2, h * 18 // 100)
        mid0, mid1 = r0 + h * 42 // 100, r0 + h * 58 // 100
        for y in range(r0, r1 + 1):
            if y < keep_top or y > keep_bot:
                continue                                       # top / bottom strokes stay
            if mid0 <= y <= mid1:
                out[y, x0:x0 + (x1 - x0 + 1) * 35 // 100] = 0  # waist: short of the left edge
                continue
            out[y, x0:cut] = 0
        return out

    def render(self, label, d, k, stock_sprite, at=None):
        """the stock sprite (pad d, style k) with its band replaced by `label`"""
        g = self.glyphs_cache[k]
        parts = [g[c] for c in label]
        spans = [_cols(p) for p in parts]
        width = sum(b - a + 1 for a, b in spans) + self.gap16 * (len(parts) - 1)
        # stock centre of this direction: the '4' pad's ink centre
        sa = self.alpha(self.P.bjs[("4", d)][k], self.bg[k], k, self.band)
        c0, c1 = _cols(sa)
        left = int(round((c0 + c1 + 1) / 2 - width / 2)) if at is None else at
        A = np.zeros((BJ["h"], W))
        x = left
        for p, (a, b) in zip(parts, spans):
            A[:, x:x + (b - a + 1)] = np.maximum(A[:, x:x + (b - a + 1)], p[:, a:b + 1])
            x += (b - a + 1) + self.gap16
        out = stock_sprite.copy()
        bg = self.bg[k].astype(np.float64)
        ink = self.ink[k]
        rows = slice(self.band.start, self.band.stop)
        cols = slice(4, 75)
        new = np.rint(bg + A[..., None] * (ink - bg)).astype(np.int32)
        out[rows, cols] = new[rows, cols]
        return np.clip(out, 0, [31, 63, 31])

    def prepare(self):
        # one set of masks for all styles: the font's anti-aliasing is the same
        # in every style (stock 1/2/4: alpha differs by <= 0.11 between styles);
        # the BEAT LOOP dim background cannot be rebuilt (no row period)
        g0 = self.glyphs(0)
        self.glyphs_cache = {k: g0 for k in range(3)}

    def validate(self):
        """stock 1/2/4, both directions, all styles: re-rendered vs stock"""
        self.prepare()
        res = {}
        for d in ("rev", "fwd"):
            for l in ("1", "2", "4"):
                for k in range(3):
                    s = self.P.bjs[(l, d)][k]
                    at = _cols(self.alpha(s, self.bg[k], k, self.band))[0]
                    got = self.render(l, d, k, s, at=at)
                    diff = np.abs(got - s)
                    res[f"{d}{l}/s{k}"] = (int(diff.max()), int(np.any(diff > 0, axis=2).sum()),
                                           int(np.any(diff > 2, axis=2).sum()))
        return res


def _cols(a):
    c = np.nonzero(a.sum(axis=0) > 0.05)[0]
    return int(c[0]), int(c[-1])


def rgb8(a):
    a = np.clip(a, 0, [31, 63, 31])
    return np.dstack([a[..., 0] * 255 // 31, a[..., 1] * 255 // 63, a[..., 2] * 255 // 31]).astype(np.uint8)


PAGES = (("1", "2", "4"), ("4", "8", "16"), ("16", "32", "64"))
OUT = os.path.join(ROOT, "work", "bjswipe", "build")


def build(L):
    """labels.bin: [page 0..2][code 1..6][style 0..2] -> the band rows of that
    sprite (row-major RGB565). Page 0 is the stock band, byte for byte."""
    L.prepare()
    r0, r1 = L.band.start, L.band.stop
    blob = bytearray()
    pads = {p["code"]: p for p in BJ["pads"]}
    stock_img = L.P.img
    for pi, sizes in enumerate(PAGES):
        for code in range(1, 7):
            p = pads[code]
            for k in range(3):
                spr = L.P.bjs[(p["label"], p["dir"])][k]
                if pi == 0:
                    a = int(p["addr"], 16) + k * BJ["style_stride"] + r0 * W * 2 - 0x08000000
                    band = stock_img[a:a + (r1 - r0) * W * 2]
                    assert band == PL.pack(spr[r0:r1])
                else:
                    band = PL.pack(L.render(sizes[(code - 1) // 2], p["dir"], k, spr)[r0:r1])
                blob += band
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "labels.bin"), "wb").write(blob)
    lay = {"pages": PAGES, "rows": [r0, r1], "band_bytes": (r1 - r0) * W * 2, "order": "page, code 1..6, style 0..2",
           "synthetic": "3 (from the firmware 8, glyph3())", "size": len(blob),
           "sha256": __import__("hashlib").sha256(blob).hexdigest()}
    json.dump(lay, open(os.path.join(OUT, "labels.json"), "w"), indent=1)
    print("labels.bin %d B, band rows %d..%d, sha256 %s" % (len(blob), r0, r1 - 1, lay["sha256"]))
    return blob, lay


def main(av):
    img = open(os.path.join(ROOT, "work", "MAIN_mk1_113.img"), "rb").read()
    L = Labels(img)
    print("background rows without a period:", {k: v for k, v in L.bad.items() if v})
    if av[:1] == ["check"]:
        for k, v in L.validate().items():
            print(f"{k}: max channel diff {v[0]}, px differing {v[1]}, px off by >2 {v[2]}")
        from PIL import Image
        rows = []
        for k in range(3):
            t = [L.P.bjs[("4", "rev")][k]]
            t += [L.render(l, d, k, L.P.bjs[("4", d)][k])
                  for l, d in (("4", "rev"), ("8", "fwd"), ("16", "rev"), ("32", "fwd"), ("64", "rev"))]
            rows.append(np.hstack([rgb8(x) for x in t]))
        im = Image.fromarray(np.vstack(rows))
        im = im.resize((im.width * 3, im.height * 3), Image.NEAREST)
        out = os.path.join(ROOT, "work", "bjswipe", "labels.png")
        im.save(out)
        print("preview", out)
    if av[:1] == ["build"]:
        build(L)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
