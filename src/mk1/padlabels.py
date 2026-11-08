#!/usr/bin/env python3
"""Relabel MK1's BEAT JUMP pad sprites using only the firmware's own pixels.

The six BEAT JUMP pads are 80x63 RGB565 sprites in the MAIN image, three
styles each (normal, lit, dim), the digit baked in. MK1's BEAT LOOP pads
(80x53, six styles: the same normal/lit/dim plus three orange) carry the
same font at the same size, and between them hold 1/2, 1, 2, 4, 8 and 16.

A label is transplanted, never drawn: in the source sprite (same style) the
glyph is its difference from that style's clean background, and the
difference is added to the target's clean background. A style's clean
background is the per-pixel majority over all pads of that style (two pads
agree wherever neither has a digit).

validate() transplants the BEAT LOOP 1, 2 and 4 onto the BEAT JUMP background
and compares them with the stock BEAT JUMP 1, 2 and 4: that is the evidence
the method reproduces the firmware's own rendering.

Addresses come from mk1/models/xdj1000_113.json ("bj_pad_sprites",
"bl_pad_sprites").
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASE = 0x08000000
MODEL = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))


def _ent(name):
    return MODEL["entries"][name]


def sprites():
    bj, bl = _ent("bj_pad_sprites"), _ent("bl_pad_sprites")
    return bj, bl


def read(img, addr, w, h):
    v = np.frombuffer(img[addr - BASE:addr - BASE + w * h * 2], dtype="<u2").reshape(h, w)
    return np.dstack([(v >> 11) & 31, (v >> 5) & 63, v & 31]).astype(np.int32)


def pack(a):
    a = np.clip(a, 0, [31, 63, 31])
    return ((a[..., 0] << 11) | (a[..., 1] << 5) | a[..., 2]).astype("<u2").tobytes()


def majority(stack):
    """Per-pixel value that at least two of the given sprites share (else -1)."""
    n = len(stack)
    out = np.full(stack[0].shape, -1, dtype=np.int32)
    done = np.zeros(stack[0].shape[:2], bool)
    for i in range(n):
        for j in range(i + 1, n):
            eq = np.all(stack[i] == stack[j], axis=2) & ~done
            out[eq] = stack[i][eq]
            done |= eq
    return out, done


class Pads:
    def __init__(self, img):
        self.img = img
        bj, bl = sprites()
        self.bj, self.bl = bj, bl
        W, Hj, Hl = bj["w"], bj["h"], bl["h"]
        self.W, self.Hj, self.Hl = W, Hj, Hl
        # BEAT JUMP: pads[label][dir][style]
        self.bjs = {}
        for p in bj["pads"]:
            self.bjs[(p["label"], p["dir"])] = [read(img, int(p["addr"], 16) + k * W * Hj * 2, W, Hj)
                                                 for k in range(bj["styles"])]
        self.bls = {p["label"]: [read(img, int(p["addr"], 16) + k * W * Hl * 2, W, Hl)
                                 for k in range(bl["styles"])] for p in bl["pads"]}
        # clean backgrounds per style (BEAT JUMP per direction: the tab differs)
        self.bj_bg = {}
        for d in ("rev", "fwd"):
            for k in range(bj["styles"]):
                st = [self.bjs[(l, d)][k] for l in ("1", "2", "4")]
                self.bj_bg[(d, k)] = majority(st)
        # the two directions place their digit ~2 px apart and share the
        # background in the digit band (99% of known pixels identical), so a
        # pixel all three digits of one direction cover is taken from the other
        for k in range(bj["styles"]):
            for d, o in (("rev", "fwd"), ("fwd", "rev")):
                bg, ok = self.bj_bg[(d, k)]
                obg, ook = self.bj_bg[(o, k)]
                fill = ~ok & ook
                fill[:15] = False                      # the tab rows differ
                bg[fill] = obg[fill]
                ok |= fill
        # Left: ~31-42 centre pixels per style that ALL of 1, 2 and 4 cover in
        # both directions. The texture is not strictly periodic there, so these
        # are ESTIMATED from the nearest known pixel of the same row and x
        # parity; self.estimated marks them and validate() measures the result.
        self.estimated = {}
        for key, (bg, ok) in self.bj_bg.items():
            est = ~ok.copy()
            for y, x in zip(*np.nonzero(~ok)):
                cands = [xx for xx in range(W) if ok[y, xx] and (xx - x) % 2 == 0]
                if cands:
                    xx = min(cands, key=lambda c: abs(c - x))
                    bg[y, x] = bg[y, xx]
            ok |= est
            self.estimated[key] = est
        self.bl_bg = {k: majority([self.bls[l][k] for l in self.bls]) for k in range(bj["styles"])}

    def glyph(self, label, k):
        """(delta, footprint) of a BEAT LOOP label in style k, rows of the loop pad."""
        src = self.bls[label][k]
        bg, ok = self.bl_bg[k]
        foot = ok & np.any(src != bg, axis=2)
        # only the label: the loop pads also differ from each other at their
        # borders, which must not travel with the glyph
        box = np.zeros_like(foot)
        y0 = self.bl["digit_y0"]
        box[y0 - 2:y0 + 18, 24:57] = True
        foot &= box
        delta = np.where(foot[..., None], src - bg, 0)
        return delta, foot

    def label_box(self):
        y0 = self.bj["digit_y0"]
        return slice(y0 - 3, y0 + 19), slice(26, 56)

    def compose(self, label, d, k, onto=None):
        """The BEAT JUMP pad that now shows `onto` (stock label of that pad,
        direction d, style k) relabelled to `label`.

        Everything outside the label box is the pad's own stock pixels. If
        `label` is itself a stock BEAT JUMP label (1, 2, 4), the whole sprite is
        that stock sprite: an exact copy. Otherwise, inside the label box: the
        old digit's pixels become the background estimate, then the BEAT LOOP
        glyph (same style) is added at the measured offset."""
        onto = onto or label
        if (label, d) in self.bjs:
            return self.bjs[(label, d)][k].copy()
        base = self.bjs[(onto, d)][k]
        bg, _ = self.bj_bg[(d, k)]
        ys_, xs_ = self.label_box()
        out = base.copy()
        old = np.zeros(base.shape[:2], bool)
        old[ys_, xs_] = np.any(base[ys_, xs_] != bg[ys_, xs_], axis=2)
        out[old] = bg[old]
        delta, foot = self.glyph(label, k)
        off = self.bj["label_offset_from_bl"][d]
        ys, xs = np.nonzero(foot)
        out[ys + off["dy"], xs + off["dx"]] = bg[ys + off["dy"], xs + off["dx"]] + delta[ys, xs]
        return np.clip(out, 0, [31, 63, 31])

    def recompose_stock(self, label, d, k):
        """validate(): a stock pad rebuilt with the BEAT LOOP glyph of its own
        label, the path an 8 or 16 takes."""
        saved = self.bjs.pop((label, d))
        self.bjs[("_" + label, d)] = saved
        try:
            return self.compose(label, d, k, onto="_" + label)
        finally:
            self.bjs[(label, d)] = self.bjs.pop(("_" + label, d))

    def validate(self):
        res = {}
        for d in ("rev", "fwd"):
            for l in ("1", "2", "4"):
                for k in range(self.bj["styles"]):
                    got = self.recompose_stock(l, d, k)
                    want = self.bjs[(l, d)][k]
                    diff = np.abs(got - want)
                    ys_, xs_ = self.label_box()
                    outside = np.any(diff > 0, axis=2)
                    outside[ys_, xs_] = False
                    inside = np.any(diff[ys_, xs_] > 0, axis=2)
                    res[f"{d}{l}/s{k}"] = (int(diff.max()), int(inside.sum()), int(outside.sum()))
        return res


def main():
    img = open(os.path.join(ROOT, "work", "MAIN_mk1_113.img"), "rb").read()
    P = Pads(img)
    for k, v in P.validate().items():
        print(f"{k}: max channel diff {v[0]}, differing pixels inside the label box {v[1]} (of 660), outside {v[2]}")


if __name__ == "__main__":
    sys.exit(main())
