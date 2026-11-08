#!/usr/bin/env python3
"""Read the REMAIN time (MM:SS.mmm) off an XDJ deck screenshot (800x480).

Template matching on the deck's own digits: the templates are cut from
screenshots whose value was read by eye and is listed in TRAIN, so a reading
is only as good as those. read() returns seconds, or None when a glyph
matches no template well (the caller treats that as a failed reading).

    usage: python3 mk1/remain_ocr.py SHOT.png [...]
"""
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOX = (280, 358, 580, 400)          # REMAIN digits (stops above the LOOP MODE pad row at y 403)
TRAIN = {                           # screenshot -> REMAIN as read by eye
    "work/trace/xdj1000/q11/base.png": "01:02.384",
    "work/trace/xdj1000/q11/code1.png": "01:02.869",
    "work/trace/xdj1000/q11/code2.png": "01:01.835",
    "work/trace/xdj1000/q11/code3.png": "01:03.430",
    "work/trace/xdj1000/q11/code5.png": "01:04.364",
    "work/trace/xdj1000/q11/table2.png": "00:54.380",
    "work/trace/xdj1000/pcall/table_code1.png": "00:57.037",
    "work/trace/xdj1000/pcall/code6.png": "00:51.099",
    "work/trace/xdj1000/pcall/code5.png": "00:55.026",
    "work/trace/xdj1000/q11/table1.png": "01:06.395",       # large 6
    "work/trace/xdj1000/pcall/code4.png": "00:52.143",      # small 1
    "work/longjump/probe/ocr_train_8.png": "00:58.342",      # large 8
}


def glyphs(path):
    a = np.asarray(Image.open(path).convert("L").crop(BOX)).astype(float)
    on = a > 128
    cols = on.any(axis=0)
    out, x = [], 0
    while x < len(cols):
        if cols[x]:
            x0 = x
            while x < len(cols) and cols[x]:
                x += 1
            g = on[:, x0:x]
            rows = np.nonzero(g.any(axis=1))[0]
            out.append(g[rows.min():rows.max() + 1])
        x += 1
    return out


SLOTS = [(12, 36), (36, 60), (70, 96), (96, 120), (128, 148), (148, 168), (168, 188)]


def digits(_unused=None, path=None):
    """The seven fixed digit slots MM SS mmm (crop coordinates), each glyph
    trimmed to its ink: digits that touch cannot merge."""
    a = np.asarray(Image.open(path).convert("L").crop(BOX)) > 128
    out = []
    for x0, x1 in SLOTS:
        g = a[:, x0:x1]
        r, c = np.nonzero(g)
        out.append(g[r.min():r.max() + 1, c.min():c.max() + 1] if len(r) else None)
    return out


def _key(g):
    return (g.shape[0] > 20, )           # big (MM:SS) vs small (.mmm) digits


def _sim(a, b):
    if abs(a.shape[0] - b.shape[0]) > 2 or abs(a.shape[1] - b.shape[1]) > 2:
        return 0.0
    h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
    A = np.zeros((h, w), bool); B = np.zeros((h, w), bool)
    A[:a.shape[0], :a.shape[1]] = a; B[:b.shape[0], :b.shape[1]] = b
    return (A & B).sum() / max((A | B).sum(), 1)


def templates():
    t = []
    for p, s in TRAIN.items():
        p = os.path.join(ROOT, p)
        if not os.path.exists(p):
            continue
        chars = [c for c in s if c.isdigit()]
        t += [(c, g) for c, g in zip(chars, digits(path=p)) if g is not None]
    return t


T = None


def read(path, min_sim=0.8):
    global T
    T = T or templates()
    gs = digits(path=path)
    if any(g is None for g in gs):
        return None
    s = ""
    for g in gs:
        best = max(T, key=lambda t: _sim(g, t[1]))
        if _sim(g, best[1]) < min_sim:
            return None
        s += best[0]
    return int(s[0:2]) * 60 + int(s[2:4]) + int(s[4:7]) / 1000.0


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p, read(p))
