#!/usr/bin/env python3
"""Colour / 3-band waveforms for tracks loaded over Pro DJ Link (mk1/lnk/lnk.c):
build + loader ops. The module sits on the media task's audio-open pool word
(models link_drive audio_open_pool) and fills the colour slots from the linked
stick's ANLZ files; rgb_mk1.py's LINK_GUARD / COPY5 patch use LINK_FLAG.
    lnk_mk1.py build      -> work/lnk/lnk.bin
"""
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import shbuild                                                  # noqa: E402

M = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
H = lambda v: int(v, 16)
X, LDRV, FA = M["lnk_module"], M["link_drive"], M["file_api"]
BASE, END_MAX, FLAG = H(X["addr"]), H(X["end_max"]), H(X["flag"])
POOL, POOL_STOCK = H(LDRV["audio_open_pool"]), H(FA["fopen_w"])
OUT = os.path.join(ROOT, "work", "lnk")


def slots():
    j = json.load(open(os.path.join(ROOT, "work", "rgb", "build", "install.json")))
    s = {k: (int(v, 16) if isinstance(v, str) else v) for k, v in j["slots"].items()}
    return dict(SLOT4=s["SLOT4"], SLOT6=s["SLOT6"], SLOT5=s["SLOT5"], SLOT5_MAX=s["SLOT5_MAX"],
                SLOT4_MAX=s["SLOT6"] - s["SLOT4"], SLOT6_MAX=0x1000, SLOT7=H(X["slot7"]), SLOT7_MAX=H(X["slot7_max"]))


def build():
    d = dict(FOPEN_W=POOL_STOCK, FREAD_C=H(FA["fread_c"]), FCLOSE_C=H(FA["fclose_c"]), LINK_FLAG=FLAG, **slots())
    src = os.path.join(HERE, "lnk")
    img, syms = shbuild.build(OUT, "lnk", [os.path.join(src, "lnkentry.S"), os.path.join(src, "lnk.c")],
                              BASE, END_MAX, d, "_lnk_head", keep=("_lnk_", "_end"),
                              extra=("-fno-tree-loop-distribute-patterns",))
    assert syms["lnk_head"] == BASE and struct.unpack_from("<I", img, 0)[0] == syms["lnk_open"], syms
    return img, syms


def ops(OP_COPY, OP_ZERO, OP_STORE):
    """loader ops: module, bss zeroed, flag zeroed, then the audio-open pool word (LAST)"""
    img, s = build()
    n = (len(img) + 3) & ~3
    out = [(OP_COPY, BASE, img, 0)]
    if s["end"] > BASE + n:
        out.append((OP_ZERO, BASE + n, ((s["end"] + 3) & ~3) - BASE - n, 0))
    return out, [(OP_STORE, POOL, POOL_STOCK, s["lnk_open"], 0)], s


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        img, s = build()
        print("lnk %d B, hook %#x, state %#x, end %#x" % (len(img), s["lnk_open"], s["lnk_st"], s["end"]))
    else:
        print(__doc__)
