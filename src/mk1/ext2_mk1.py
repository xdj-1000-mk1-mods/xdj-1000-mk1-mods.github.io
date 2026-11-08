#!/usr/bin/env python3
"""3-BAND from rekordbox's ANLZ0000.2EX (mk1/ext2/ext2.c): build + install ops.

    ext2_mk1.py build      -> work/ext2/ext2.bin
The module wraps the .EXT parse (models ext_parse: pool word -> wrapper) and
appends PWV6/PWV7 from .2EX to the ANLZ extra-section index when .EXT lacks them.
Installed from the stick (loader ops): COPY module, then STORE the pool word.
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
X, P, FA = M["ext2_module"], M["ext_parse"], M["file_api"]
BASE, END_MAX = H(X["addr"]), H(X["end_max"])
POOL, POOL_STOCK = H(P["pool"]), H(P["pool_stock"])
OUT = os.path.join(ROOT, "work", "ext2")


def build(settings=None):
    d = dict(PARSE_STOCK=POOL_STOCK, IDX_OFF=H(M["anlz_ctx_table"]["extra_index_off"]),
             EXT_PATH_OFF=H(M["anlz_ctx_paths"]["ext_path_off"]), DAT_PATH_OFF=H(M["anlz_ctx_paths"]["dat_path_off"]), IDX_CAP=M["anlz_ctx_paths"]["index_capacity"],
             FOPEN_W=H(FA["fopen_w"]), FREAD_C=H(FA["fread_c"]), FCLOSE_C=H(FA["fclose_c"]),
             BUF=H(X["buf"]), BUF_END=H(X["buf_end"]), DRIVE_WORD=H(X["drive_word"]), SCAN_LEN=0x800)
    if settings:                                   # stick settings write side (mods_all.cfg_defs)
        d.update(settings, FWRITE_C=H(FA["fwrite_c"]))
    src = os.path.join(HERE, "ext2")
    img, syms = shbuild.build(OUT, "ext2", [os.path.join(src, "ext2entry.S"), os.path.join(src, "ext2.c")],
                              BASE, END_MAX, d, "_ext2_head", keep=("_ext2_", "_end"),
                              extra=("-fno-tree-loop-distribute-patterns",))
    assert syms["ext2_head"] == BASE and struct.unpack_from("<I", img, 4)[0] == syms["ext2_parse"], syms
    assert syms["end"] <= END_MAX
    return img, syms


def ops(OP_COPY, OP_ZERO, OP_STORE, settings=None):
    """loader ops: module (code: cached + RAM), bss zeroed, then the parse pool word (LAST)"""
    img, s = build(settings)
    n = (len(img) + 3) & ~3
    out = [(OP_COPY, BASE, img, 0)]
    if s["end"] > BASE + n:
        out.append((OP_ZERO, BASE + n, ((s["end"] + 3) & ~3) - BASE - n, 0))
    return out, [(OP_STORE, POOL, POOL_STOCK, s["ext2_parse"], 0)], s


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        img, s = build()
        print("ext2 %d B, parse wrapper %#x, state %#x" % (len(img), s["ext2_parse"], s["ext2_st"]))
    else:
        print(__doc__)
