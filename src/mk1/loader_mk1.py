#!/usr/bin/env python3
"""Stick loader for the XDJ-1000 MK1: installs the RAM mods from <stick>/MODS.BIN.

    loader_mk1.py build [SNAPDIR]     loader module + MODS.BIN (from a snapshot bundle,
                                      default mk1/snapshots/2026-11-02) -> work/loader/
    loader_mk1.py emu [CASE ...]      qemu cold boot, loader poked in before the CPU runs,
                                      stick mounted at boot. CASES: ok refuse badcrc nofile
                                      (default all). MK1_JUNK=... pre-fills the RAM home.

The loader (mk1/loader/ldr.c) hooks the stick mount check's path_build pool word
(models stick_mount_check). MODS.BIN = header + ops, the same plan as the snapshot's
install.py (rgb + UTILITY rows + phase meter), plus CHECK track_len == 0: a deck with
a track loaded is refused (nothing written, a later stick insert retries).
"""
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import shbuild                                                  # noqa: E402

M = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
H = lambda v: int(v, 16)
L, MC = M["stick_loader"], M["stick_mount_check"]
BASE, END_MAX, STATE = H(L["addr"]), H(L["end_max"]), H(L["state"])
STAGE, STAGE_END = H(L["stage"]), H(L["stage_end"])
POOL, POOL_STOCK = H(MC["path_build_pool"]), H(MC["path_build_pool_stock"])
FREE = (0x09800000, 0x09A00000)                                 # deck survey 2026-11-01 (= bundle 'free')
TRACK_LEN = H(M["track_len_word"]["addr"])
OUT = os.path.join(ROOT, "work", "loader")
SNAP = os.environ.get("XDJMOD_SNAP") or os.path.join(HERE, "snapshots", "2026-11-06")
NXS2 = os.environ.get("XDJMOD_NXS2") or os.path.normpath(os.path.join(ROOT, "..", "..", "cdj-nxs2"))
STATUS = ["IDLE", "RUN", "OK", "NOFILE", "TOOBIG", "BADHDR", "BADCRC", "BADOP", "NOTSTOCK", "MIDWAY"]
OP_END, OP_CHECK, OP_COPY, OP_ZERO, OP_MEMCPY, OP_STORE = range(6)


def build():
    d = dict(PB_STOCK=POOL_STOCK, OPEN_R=H(L["open_r"]), READ_DB=H(L["read_db"]), CLOSE_DB=H(L["close_db"]),
             NAME_PDB=H(L["name_pdb"]), STATE=STATE, STAGE=STAGE, STAGE_END=STAGE_END,
             FREE_LO=FREE[0], FREE_HI=FREE[1], LDR_LO=BASE)
    src = os.path.join(HERE, "loader")
    img, syms = shbuild.build(OUT, "ldr", [os.path.join(src, "ldrentry.S"), os.path.join(src, "ldr.c")],
                              BASE, END_MAX, d, "_ldr_head", keep=("_ldr_", "_end"),
                              extra=("-fno-tree-loop-distribute-patterns",))
    assert syms["ldr_head"] == BASE and struct.unpack_from("<I", img, 4)[0] == syms["ldr_path_build"], syms
    return img, syms


def bake(dec, log=print):
    """flash form: the loader rides on permanent_mk1's boot copier (init-hook pool,
    after the .data copy, caches off): zero its state, copy the module, and the
    mount check's pool word (in the image) -> loader entry. Nothing else changes."""
    import permanent_mk1 as PM
    img, s = build()
    m = PM.Img(dec)
    assert m.r32(POOL) == POOL_STOCK, "path_build pool not stock in the image"
    m.zero_fill(STATE, 0x100)
    m.write(BASE, img)
    m.write(POOL, struct.pack("<I", s["ldr_path_build"]))
    tail, jobs, n = PM.boot_tail(m)
    log("loader: module %#x (+%d B), state %#x zeroed, pool %#x -> %#x; boot copier %d jobs at %#x (+%d B)"
        % (BASE, len(img), STATE, POOL, s["ldr_path_build"], len(jobs), tail, n))
    return s


# ---------------------------------------------------------------- MODS.BIN
def plan(snap=SNAP, track_want=0, mode=None, ext2=False):
    """ops in install order, mirroring snapshot install.py rgb() then phasemeter();
    mode: waveform mode word override (0 BLUE, 1 RGB, 2 3-BAND); ext2: + 3-BAND from .2EX"""
    ops = _plan(snap, track_want, mode)
    if ext2:
        import ext2_mk1
        blocks, hooks, _ = ext2_mk1.ops(OP_COPY, OP_ZERO, OP_STORE)
        ops = ops + blocks + hooks
    return ops


def _plan(snap, track_want, mode):
    B = json.load(open(os.path.join(snap, "bundle.json")))
    assert (H(B["free"][0]), H(B["free"][1])) == FREE, B["free"]
    blob = lambda n: open(os.path.join(snap, "bin", n), "rb").read()
    R, U, P = B["rgb"], B["utility"], B["phasemeter"]
    ops = [(OP_CHECK, H(B["track_len"]), track_want)]              # no track loaded
    for x in R["blocks"]:
        ops.append((OP_COPY, H(x["addr"]), blob(x["file"]), 0))
    for x in R["zeros"]:
        ops.append((OP_ZERO, H(x["addr"]), x["len"], 0))
    ops.append((OP_COPY, H(R["mode"][0]), struct.pack("<I", H(R["mode"][1]) if mode is None else mode), 0))
    ops.append((OP_COPY, H(U["base"]), blob(U["file"]), 0))
    ops.append((OP_MEMCPY, H(U["tab"]), H(U["stock_tab"]), U["nstock"] * U["rec"], 0))  # the deck's own rows
    for x in R["hooks"]:
        ops.append((OP_STORE, H(x["addr"]), H(x["stock"]), H(x["new"]), 0))
    for p in U["pools"]:
        ops.append((OP_STORE, H(p), H(U["stock_tab"]), H(U["tab"]), 1))
    ops.append((OP_STORE, H(U["count"]), U["nstock"], U["n"], 1))
    ops.append((OP_COPY, H(P["base"]), blob(P["file"]), 0))
    ops.append((OP_ZERO, H(P["state_addr"]), P["state_len"], 1))
    pm = H(P["pm_mode"])
    ops.append((OP_COPY, pm & ~3, struct.pack("<I", 1 << (8 * (pm & 3))), 1))
    ops.append((OP_ZERO, H(P["flags_addr"]), P["flags_len"], 1))
    ops.append((OP_STORE, H(P["hook"]), H(P["stock"]), H(P["base"]), 0))
    return ops


def pack(ops, cap=None):
    body = b""
    for o in ops:
        k = o[0]
        if k == OP_CHECK:
            body += struct.pack("<3I", *o)
        elif k == OP_COPY:
            data = o[2] + bytes(-len(o[2]) % 4)
            body += struct.pack("<4I", k, o[1], len(data), o[3]) + data
        elif k == OP_ZERO:
            assert o[2] % 4 == 0
            body += struct.pack("<4I", *o)
        elif k in (OP_MEMCPY, OP_STORE):
            body += struct.pack("<5I", *o)
    body += struct.pack("<I", OP_END)
    total = 16 + len(body)
    assert total < (cap or STAGE_END - STAGE), "%d B > stage" % total
    return struct.pack("<4I", 0x53444F4D, 1, total, zlib.crc32(body)) + body


def make_stick(name, mods, base="device_3band"):
    """test stick = work/testusb/<base> (+ MODS.BIN) via cdj-nxs2's image script;
    'device' = the plain rekordbox export (PWV6/PWV7 only in .2EX)"""
    src = os.path.join(OUT, "stick_" + name)
    shutil.rmtree(src, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "work", "testusb", base), src)
    if mods is not None:
        open(os.path.join(src, "MODS.BIN"), "wb").write(mods)
    img = os.path.join(OUT, "stick_%s.img" % name)
    subprocess.run([os.path.join(NXS2, ".venv", "bin", "python"),
                    os.path.join(NXS2, "scripts", "media", "make_usb_image.py"), src, img, "64"],
                   check=True, cwd=NXS2, stdout=subprocess.DEVNULL)
    return img


def cmd_build(snap=SNAP):
    img, syms = build()
    ops = plan(snap)
    mods = pack(ops)
    open(os.path.join(OUT, "MODS.BIN"), "wb").write(mods)
    import hashlib
    for n in ("ldr.bin", "MODS.BIN"):
        b = open(os.path.join(OUT, n), "rb").read()
        print("%-9s %6d B  sha256 %s" % (n, len(b), hashlib.sha256(b).hexdigest()))
    print("loader entry %#x, state %#x, %d ops, from %s" % (syms["ldr_path_build"], STATE, len(ops),
                                                           os.path.relpath(snap, ROOT)))
    return img, syms, ops, mods


# ---------------------------------------------------------------- qemu
def emu_case(case, img, syms, ops, mods, junk=None, kernel=None):
    import emu as E
    model = "xdj1000"
    want_ok = case in ("ok", "3band")
    if case == "ok":
        stick = make_stick("ok", mods)
    elif case == "3band":                                        # plain export: 3-band only in .2EX
        ops = plan(mode=2, ext2=True)
        mods = pack(ops)
        stick = make_stick("3band", mods, base="device")
    elif case == "refuse":                                       # = a track-loaded deck: CHECK fails
        stick = make_stick("refuse", pack([(OP_CHECK, TRACK_LEN, 1)] + plan()[1:]))
    elif case == "badcrc":
        b = bytearray(mods)
        b[len(b) // 2] ^= 0x01
        stick = make_stick("badcrc", bytes(b))
    else:
        stick = make_stick("nofile", None)
    stores = [o for o in ops if o[0] == OP_STORE]
    p = E.start(model, stick=stick, paused=True, kernel=kernel)
    ok = True

    def chk(label, good):
        print(("  ok   " if good else "  FAIL ") + "[%s] %s" % (case, label), flush=True)
        return bool(good)

    def u32(a):
        return struct.unpack("<I", E.peek(model, a, 4))[0]

    try:
        g = E.Gdb(model)                                         # one session, VM still stopped (-S)
        if junk:
            jb = open(junk, "rb").read()
            for o in range(0, len(jb), 0x200):
                g.wr(FREE[0] + o, jb[o:o + 0x200])
        if kernel:                                               # flash image: its boot copier places the loader
            assert g.rd(POOL, 4) == struct.pack("<I", syms["ldr_path_build"]), "flash image pool word not the loader"
        else:                                                    # RAM install, as deck_write.py loader does
            for o in range(0, len(img), 0x200):
                g.wr(BASE + o, img[o:o + 0x200])
            assert g.rd(POOL, 4) == struct.pack("<I", POOL_STOCK), "pool word not stock before boot"
            g.wr(POOL, struct.pack("<I", syms["ldr_path_build"]))
        g.detach()
        E.cmd(model, "cont")
        t0, st = time.time(), None
        while time.time() - t0 < 180:
            time.sleep(3)
            try:
                if u32(STATE) == 0x5453444C and u32(STATE + 8) not in (0, 1):
                    st = struct.unpack("<11I", E.peek(model, STATE, 44))
                    break
            except Exception:
                pass
        if st is None:
            st = struct.unpack("<11I", E.peek(model, STATE, 44))
        name = STATUS[st[2]] if st[2] < len(STATUS) else hex(st[2])
        print("  [%s] state: status %s mounts %d attempts %d flen %d nops %d bad %#x got %#x want %#x"
              " (%.0f s)" % (case, name, st[3], st[4], st[5], st[6], st[7], st[8], st[9], time.time() - t0))
        expect = {"ok": "OK", "3band": "OK", "refuse": "NOTSTOCK", "badcrc": "BADCRC", "nofile": "NOFILE"}[case]
        ok &= chk("loader ran on mount, status %s (want %s)" % (name, expect), st[3] >= 1 and name == expect)
        ok &= chk("done marker %s" % ("set" if want_ok else "not set"), (st[1] == 0x454E4F44) == want_ok)
        if case == "refuse":
            ok &= chk("refused on track_len %#x" % st[7], st[7] == TRACK_LEN)
        got = [(o[1], u32(o[1])) for o in stores]
        if want_ok:
            bad = [hex(a) for (a, v), o in zip(got, stores) if v != o[3]]
            ok &= chk("%d hook/pool/count words = new%s" % (len(stores), "" if not bad else " BAD " + str(bad)), not bad)
            code = [o for o in ops if o[0] == OP_COPY and o[3] == 0]
            diff = []
            for o in code:
                g2 = E.peek(model, o[1], len(o[2]))
                n = sum(1 for i in range(0, len(o[2]), 4) if g2[i:i + 4] != o[2][i:i + 4])
                if n:
                    diff.append("%#x:%d" % (o[1], n))
            ok &= chk("%d copied blocks as built (words differing, may be live state: %s)"
                      % (len(code), diff or "none"), len(diff) <= 2)
            print("  [%s] differing blocks (expected only module data words): %s" % (case, diff), flush=True)
        else:
            bad = [hex(a) for (a, v), o in zip(got, stores) if v != o[2]]
            ok &= chk("nothing written: %d hook words still stock%s" % (len(stores), "" if not bad else " BAD " + str(bad)),
                      not bad)
        shots = os.path.join(OUT, "shots")
        os.makedirs(shots, exist_ok=True)
        time.sleep(5)
        for s in ("key 0x13:0x04:300", 12, "rot 1", 3, "rot 1", 3,       # USB, 2nd entry, load + play
                  "key 0x11:0x01:300", 12, "key 0x11:0x01:300", 15):
            E.step(model, s) if isinstance(s, str) else time.sleep(s)
        E.shot(model, os.path.join(shots, "%s_track.png" % case))
        ok &= chk("track loads afterwards (len %d), deck running" % u32(TRACK_LEN),
                  u32(TRACK_LEN) != 0 and "running" in E.cmd(model, "info status"))
        if case == "3band":
            import ext2_mk1
            _, xs = ext2_mk1.build()
            xst = struct.unpack("<8I", E.peek(model, xs["ext2_st"], 32))
            print("  [3band] ext2 saw path len %d %r" % (xst[7], E.peek(model, xs["ext2_st"] + 32, 48)), flush=True)
            ctx = u32(H(M["anlz_ctx_table"]["addr"])) & 0x1FFFFFFF
            ix = ctx + H(M["anlz_ctx_table"]["extra_index_off"])
            n = u32(ix)
            ents = [struct.unpack("<4I", E.peek(model, ix + 4 + 16 * k, 16)) for k in range(min(n, 32))]
            tags = [e[1].to_bytes(4, "little").decode("latin1") for e in ents]
            print("  [3band] ext2 state: calls %d status %d added %d flen %d drive %r; index %s"
                  % (xst[1], xst[2], xst[3], xst[4], chr(xst[6]) if xst[6] else "", tags), flush=True)
            ins = [e for e in ents if e[1] in (0x36565750, 0x37565750)]
            okp = all(H(M["ext2_module"]["buf"]) <= e[3] < H(M["ext2_module"]["buf_end"]) and e[3] % 4 == 0
                      and E.peek(model, e[3], 4) == e[1].to_bytes(4, "little") for e in ins)
            ok &= chk("PWV6 + PWV7 from .2EX in the index, pointers aligned into the buffer at the section tag",
                      len(ins) == 2 and okp and xst[2] == 6)
        if want_ok:
            st2 = struct.unpack("<11I", E.peek(model, STATE, 44))
            ok &= chk("no second install (attempts %d, mounts %d)" % (st2[4], st2[3]), st2[4] == 1)
    finally:
        try:
            E.cmd(model, "quit")
        except OSError:
            pass
        p.wait(timeout=60)
    return ok


def main(av):
    if not av or av[0] not in ("build", "emu"):
        print(__doc__)
        return 1
    if av[0] == "build":
        cmd_build(av[1] if len(av) > 1 else SNAP)
        return 0
    img, syms, ops, mods = cmd_build()
    kernel = None
    if "--kernel" in av:                                         # a flash image built with build_mk1.py loader
        i = av.index("--kernel")
        kernel = os.path.abspath(av[i + 1])
        del av[i:i + 2]
    cases = av[1:] or ["ok", "refuse", "badcrc", "nofile"]
    res = {}
    for c in cases:
        res[c] = emu_case(c, img, syms, ops, mods, junk=os.environ.get("MK1_JUNK"), kernel=kernel)
    for c in cases:
        print("%-7s %s" % (c, "PASS" if res[c] else "FAIL"))
    print("RESULT:", "PASS" if all(res.values()) else "FAIL")
    return 0 if all(res.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
