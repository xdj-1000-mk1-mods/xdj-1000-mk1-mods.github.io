#!/usr/bin/env python3
"""GATED RAM writes to a connected XDJ-1000 MK1 over its USB debug shell.

RAM only, never flash: a power cycle undoes everything this tool does
(confirmed 2026-11-01: a test word at 0x099ffff0 was gone after a power cycle).
CLAUDE.md rule 1: run the writing commands only with the user's explicit OK.

The shell's LW (table entry 'WL' at 0x0806dc34 + 0x24, handler 0x08acf200):
`addr,valueLW` -> addr & ~3, ONE mov.l store (atomic for a hook word); the
deck replies 'R'. Gates, all checked before anything is sent:
  * blocks: only inside the deck-surveyed free RAM 0x09800000-0x09A00000
    (models ram_home_candidate.hardware), 4-aligned words
  * hooks: only words listed in HOOKS, only stock -> mod value, and only if
    the deck holds the stock value right now
  * every write is read back; anything unexpected stops the run
  * every write is appended to work/logs/deck_writes.log

Cache: whether the deck runs its data cache in copy-back or write-through
for P0 is not settled, and the CPU fetches code from RAM, not from the data
cache. So blocks (code and data) are written through the cached address
AND its uncached P2 alias (0xA0000000 | addr, same RAM), and both views are
read back: RAM and data cache then agree in either mode. Hook words are
data the firmware reads through the cache: one cached LW.

    deck_write.py noop ADDR             rewrite ADDR's own value (proves LW)
    deck_write.py lw ADDR VALUE         one word in the free range, read back
    deck_write.py rgb-overview          READ-ONLY dry run: checks + the plan
    deck_write.py rgb-overview --go     install the RGB overview (blocks, zeroes,
                                        mode RGB, then the hook as the last write)
    deck_write.py phasemeter [--go]     phase meter on the display-flush hook
    deck_write.py rgb-full [--go]       overview + centre + PERFORM strip + UTILITY
                                        WAVEFORM COLOR row; only right after a power
                                        cycle with NO track loaded (refuses otherwise)
    deck_write.py loader [--go]         stick loader (loader_mk1.py): module at 0x09900000,
                                        state zeroed, then the mount check's path_build
                                        pool word -> loader (LAST). Then insert a stick
                                        with MODS.BIN: the loader installs the mods.
    deck_write.py loader-status         READ-ONLY: loader state + mod hook words
    deck_write.py pm-status             READ-ONLY: phase meter state (beat grid, master row)
"""
import json
import os
import re
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import deck_read as D                                          # noqa: E402

LOG = os.path.join(ROOT, "work", "logs", "deck_writes.log")
MODEL = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
RGB_DIR = os.path.join(ROOT, "work", "rgb", "build")
P2 = 0xA0000000
# deck survey 2026-11-01: untouched by the firmware
FREE = (0x09800000, 0x09A00000)
OP = MODEL["overview_painter"]
# hook words: addr -> (stock, mod value, what); values from the model table
HOOKS = {int(OP["release_slot"], 16): (int(OP["release_fn"], 16), 0x09800000,
                                       "overview painter release-call pool -> RGB cave")}


def in_free(a, n=4):
    a0 = a & ~P2 if a >= P2 else a
    return FREE[0] <= a0 and a0 + n <= FREE[1] and (a < P2 or a - a0 == P2)


def _cmd(h, q):
    h.write(b"\x00" + (q + b"\x00").ljust(64, b"\x00"))


def _lw(h, addr, val):
    """the ONLY write this tool sends; callers have gated addr"""
    assert addr % 4 == 0
    q = b"%x,%xLW\r" % (addr, val & 0xFFFFFFFF)
    _cmd(h, q)
    return D._drain(h, 1.0, lambda o: b"\n" in o.replace(b"\x00", b""))


def br(h, addr, n):
    """BR read; P0 RAM via deck_read, the P2 alias of the free range here"""
    if read_ok(addr, n):                                     # the deck's UTILITY table / count (0x14...)
        return raw_br(h, addr, n)
    if addr < P2:
        return D.br(h, addr, n)[0]
    if not in_free(addr, n):
        raise SystemExit("deck_write: read %#x+%d outside the free range's P2 alias" % (addr, n))
    _cmd(h, b"%x,%xBR\r" % (addr, n - 1))
    pat = re.compile(rb"\b[0-9A-Fa-f]{2}\b")

    def done(o):
        t = o.replace(b"\x00", b"")
        return len(pat.findall(t.split(b"BR")[-1])) >= n and (b"\n" in t or b"\r" in t)
    raw = D._drain(h, 6.0, done)
    t = raw.replace(b"\x00", b"")
    vals = pat.findall(t.split(b"BR")[-1]) if b"BR" in t else pat.findall(t)
    if len(vals) < n:
        raise IOError("short BR reply for %#x+%d" % (addr, n))
    return bytes(int(v, 16) for v in vals[-n:])


def rd32(h, addr):
    return struct.unpack("<I", br(h, addr, 4))[0]


def read_block(h, addr, n):
    out = bytearray()
    while len(out) < n:
        k = min(40, n - len(out))
        out += br(h, addr + len(out), k)
    return bytes(out)


def log(line):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, "a").write(time.strftime("%Y-%m-%d %H:%M:%S  ") + line + "\n")
    print(line, flush=True)


def write_word(h, addr, val, tag=""):
    """one word in the free range (cached only), read back"""
    if addr % 4 or not in_free(addr):
        raise SystemExit("deck_write: %#x is not an aligned word in the free range" % addr)
    old = rd32(h, addr)
    reply = _lw(h, addr, val)
    new = rd32(h, addr)
    log("%#010x  %#010x -> %#010x  read back %#010x  %s  [%s] reply %r" % (
        addr, old, val, new, "OK" if new == val else "MISMATCH", tag, D.text(reply)[:20]))
    if new != val:
        raise SystemExit("deck_write: read-back mismatch at %#x, stopping" % addr)


def write_block(h, addr, data, tag, cached_only=False):
    """data (padded to whole words) via the cached address AND the P2 alias,
    then both views read back (cached_only: data-only areas, cached LW + read)"""
    data = bytes(data) + bytes(-len(data) % 4)
    if addr % 4 or not in_free(addr, len(data)):
        raise SystemExit("deck_write: block %#x+%d outside the free range" % (addr, len(data)))
    for i in range(0, len(data), 4):
        v = struct.unpack_from("<I", data, i)[0]
        _lw(h, addr + i, v)
        if not cached_only:
            _lw(h, P2 | (addr + i), v)
    got0 = read_block(h, addr, len(data))
    got2 = got0 if cached_only else read_block(h, P2 | addr, len(data))
    ok = got0 == data and got2 == data
    log("%#010x +%#x  block %s: cached view %s, RAM (P2) view %s  [%s]" % (
        addr, len(data), "OK" if ok else "MISMATCH", got0 == data, got2 == data, tag))
    if not ok:
        raise SystemExit("deck_write: block read-back mismatch at %#x, stopping" % addr)


def write_hook(h, addr, val):
    if addr not in HOOKS:
        raise SystemExit("deck_write: %#x is not an allowed hook word" % addr)
    stock, mod, what = HOOKS[addr]
    if val != mod:
        raise SystemExit("deck_write: hook %#x only takes %#x" % (addr, mod))
    old = rd32(h, addr)
    if old != stock:
        raise SystemExit("deck_write: hook %#x holds %#x, not stock %#x: refusing" % (addr, old, stock))
    reply = _lw(h, addr, val)
    new = rd32(h, addr)
    log("%#010x  HOOK %#010x -> %#010x  read back %#010x  %s  [%s] reply %r" % (
        addr, old, val, new, "OK" if new == val else "MISMATCH", what, D.text(reply)[:20]))
    if new != val:
        raise SystemExit("deck_write: hook read-back mismatch at %#x" % addr)


def rgb_overview_plan():
    """the RAM install of the RGB overview (rgb_mk1.install_script order:
    blocks, zeroed areas, the mode word, the hook LAST)"""
    j = json.load(open(os.path.join(RGB_DIR, "install.json")))
    blocks = [(int(b["addr"], 16), open(os.path.join(RGB_DIR, b["file"]), "rb").read(), b["file"])
              for b in j["blobs"] if b["file"] in ("overview_cave.bin", "copy5.bin")]
    # every zero-first area (all in the free range; zeroing free RAM costs nothing and keeps
    # copy5's SLOT7 header and the cave state words defined)
    zeros = [(int(z["addr"], 16) & ~3, (int(z["addr"], 16) % 4 + z["len"] + 3) & ~3, k)
             for k, z in j["zero_first"].items()]
    mode = int(j["mode_addr"], 16)
    assert mode % 4 == 0
    hooks = [h for h in j["hooks"] if h["what"].startswith("overview")]
    assert len(hooks) == 1
    ha, hv = int(hooks[0]["addr"], 16), int(hooks[0]["value"], 16)
    assert ha in HOOKS and HOOKS[ha][1] == hv and int(hooks[0]["stock"], 16) == HOOKS[ha][0]
    return blocks, zeros, (mode, 0x00000001), (ha, hv)       # mode 1 = RGB, THEME_FLAG/P5FLAG 0


def rgb_overview(h, go):
    blocks, zeros, (mode, mval), (ha, hv) = rgb_overview_plan()
    print("plan (RGB overview, %s):" % ("INSTALL" if go else "dry run, nothing written"))
    for a, b, f in blocks:
        print("  block  %#010x +%#06x  %s" % (a, len(b), f))
    for a, n, k in zeros:
        print("  zero   %#010x +%#06x  %s" % (a, n, k))
    print("  word   %#010x = %#010x  mode RGB (THEME_FLAG, P5FLAG = 0)" % (mode, mval))
    print("  hook   %#010x  %#010x -> %#010x  (LAST)" % (ha, HOOKS[ha][0], hv))
    cur = rd32(h, ha)
    print("deck: hook word %#010x = %#010x (%s)" % (ha, cur, "stock" if cur == HOOKS[ha][0]
          else "ALREADY HOOKED" if cur == hv else "UNEXPECTED"))
    if cur != HOOKS[ha][0]:
        raise SystemExit("deck_write: hook word not stock; nothing written")
    if not go:
        print("dry run only: rerun with --go to install")
        return
    for a, b, f in blocks:
        write_block(h, a, b, f)
    for a, n, k in zeros:
        write_block(h, a, bytes(n), "zero " + k)
    write_block(h, mode, struct.pack("<I", mval), "mode word")
    write_hook(h, ha, hv)
    log("rgb-overview installed (reboot = stock)")


UT_READ = None                                               # (start, end) of the deck's UTILITY table read


def full_plan():
    """RGB overview + centre + PERFORM strip + the UTILITY rows. Hook words come
    from the RGB build (install.json, built from the model table) and the model's
    utility_table; each is a whole 32-bit word: (addr, stock word, new word, what),
    stock taken from the unpacked v1.13 image, so a halfword patch keeps its
    neighbour. Order = install order; everything is checked against the deck first."""
    global UT_READ
    import utility_mk1 as UT
    img = open(os.path.join(ROOT, "work", "MAIN_mk1_113.img"), "rb").read()
    w32 = lambda a: struct.unpack_from("<I", img, a - 0x08000000)[0]
    j = json.load(open(os.path.join(RGB_DIR, "install.json")))
    blocks = [(int(b["addr"], 16), open(os.path.join(RGB_DIR, b["file"]), "rb").read(), b["file"])
              for b in j["blobs"]]
    zeros = [(int(z["addr"], 16) & ~3, (int(z["addr"], 16) % 4 + z["len"] + 3) & ~3, k)
             for k, z in j["zero_first"].items()]
    hooks = []
    for hk in j["hooks"]:                                    # overview, centre pool/insn/rowinc, strip ...
        a, n, v, st = int(hk["addr"], 16), hk["size"], int(hk["value"], 16), int(hk["stock"], 16)
        wa = a & ~3
        stock = w32(wa)
        if n == 4:
            assert stock == st, hk
            new = v
        else:
            sh = 8 * (a - wa)
            assert (stock >> sh) & 0xFFFF == st, hk
            new = (stock & ~(0xFFFF << sh)) | (v << sh)
        hooks.append((wa, stock, new, hk["what"]))
    ut_img, s = UT.build()
    ut = dict(base=UT.BASE, end=(s["end"] + 3) & ~3, tab=s["ut_tab"], img=ut_img, stock_tab=UT.TAB,
              nstock=UT.NSTOCK, rec=UT.REC, count=UT.COUNT, n=UT.NSTOCK + UT.NOURS)
    for p in UT.POOLS:                                       # table pools: after the module, before the count
        assert w32(p) == UT.TAB, hex(p)
    ut_hooks = [(p, UT.TAB, s["ut_tab"], "UTILITY table pool -> module table") for p in UT.POOLS]
    UT_READ = (UT.TAB, UT.COUNT + 4)
    return blocks, zeros, (int(j["mode_addr"], 16), 0x00000001), hooks, ut, ut_hooks


def UT_READ_SET():
    global UT_READ
    c = int(MODEL["utility_table"]["count"], 16)
    UT_READ = (int(MODEL["utility_table"]["ram_table"], 16), c + 4)


def read_ok(addr, n):
    return UT_READ and UT_READ[0] <= addr and addr + n <= UT_READ[1]


def write_listed(h, addr, stock, new, what, cached_only=False):
    """a listed word: refuse unless the deck holds `stock`; LW cached, then the
    P2 alias (RAM) for code/image words; both views read back"""
    old = rd32(h, addr)
    if old != stock:
        raise SystemExit("deck_write: %#x holds %#x, not stock %#x: refusing [%s]" % (addr, old, stock, what))
    _lw(h, addr, new)
    if not cached_only:
        _lw(h, P2 | addr, new)
    got0 = rd32(h, addr)
    got2 = got0 if cached_only else struct.unpack("<I", raw_br(h, P2 | addr, 4))[0]
    ok = got0 == new and got2 == new
    log("%#010x  HOOK %#010x -> %#010x  cached %#010x RAM %#010x  %s  [%s]" % (
        addr, old, new, got0, got2, "OK" if ok else "MISMATCH", what))
    if not ok:
        raise SystemExit("deck_write: read-back mismatch at %#x" % addr)


def raw_br(h, addr, n):
    """BR of a P2 alias of an image word (hook read-back); fixed 4-byte reads"""
    _cmd(h, b"%x,%xBR\r" % (addr, n - 1))
    pat = re.compile(rb"\b[0-9A-Fa-f]{2}\b")

    def done(o):
        t = o.replace(b"\x00", b"")
        return len(pat.findall(t.split(b"BR")[-1])) >= n and (b"\n" in t or b"\r" in t)
    t = D._drain(h, 6.0, done).replace(b"\x00", b"")
    vals = pat.findall(t.split(b"BR")[-1]) if b"BR" in t else pat.findall(t)
    if len(vals) < n:
        raise IOError("short BR reply for %#x" % addr)
    return bytes(int(v, 16) for v in vals[-n:])


def rgb_full(h, go):
    blocks, zeros, (mode, mval), hooks, ut, ut_hooks = full_plan()
    print("plan (RGB overview + centre + PERFORM strip + UTILITY row, %s):"
          % ("INSTALL" if go else "dry run, nothing written"))
    for a, b, f in blocks:
        print("  block  %#010x +%#06x  %s" % (a, len(b), f))
    for a, n, k in zeros:
        print("  zero   %#010x +%#06x  %s" % (a, n, k))
    print("  word   %#010x = %#010x  mode RGB" % (mode, mval))
    print("  block  %#010x +%#06x  UTILITY module (+ the deck's 16 stock rows at %#x)"
          % (ut["base"], ut["end"] - ut["base"], ut["tab"]))
    for a, st, nw, what in hooks + ut_hooks:
        print("  hook   %#010x  %#010x -> %#010x  %s" % (a, st, nw, what))
    print("  word   %#010x  %d -> %d  UTILITY row count (LAST)" % (ut["count"], ut["nstock"], ut["n"]))
    # read-only checks
    tl = rd32(h, int(MODEL["track_len_word"]["addr"], 16))
    bad = [(a, rd32(h, a), st) for a, st, nw, what in hooks + ut_hooks]
    bad = [(a, cur, st) for a, cur, st in bad if cur != st]
    cnt = struct.unpack("<I", br_any(h, ut["count"], 4))[0]
    stock_rows = read_any(h, ut["stock_tab"], ut["nstock"] * ut["rec"])
    img = open(os.path.join(ROOT, "work", "MAIN_mk1_113.img"), "rb").read()
    src = int(MODEL["utility_table"]["image_table"], 16) - 0x08000000
    same = stock_rows == img[src:src + len(stock_rows)]
    print("deck: track loaded: %s (track_len %d); hook words not stock: %s; UTILITY count %d; "
          "deck's 16 rows %s the image's .data source"
          % ("YES" if tl else "no", tl, ["%#x=%#x" % (a, c) for a, c, s_ in bad] or "none", cnt,
             "==" if same else "DIFFER from"))
    if tl:
        raise SystemExit("deck_write: a track is loaded. Power-cycle, do NOT load a track, then rerun "
                         "(the centre painter must not have run since boot)")
    if bad or cnt != ut["nstock"]:
        raise SystemExit("deck_write: deck not in the stock state; nothing written")
    if not go:
        print("dry run only: rerun with --go to install")
        return
    for a, b, f in blocks:
        write_block(h, a, b, f)
    for a, n, k in zeros:
        write_block(h, a, bytes(n), "zero " + k)
    write_block(h, mode, struct.pack("<I", mval), "mode word")
    ub = bytearray(ut["img"])
    off = ut["tab"] - ut["base"]
    ub[off:off + len(stock_rows)] = stock_rows
    ub += bytes(ut["end"] - ut["base"] - len(ub))
    write_block(h, ut["base"], ub, "UTILITY module + deck rows")
    for a, st, nw, what in hooks:                            # pool before its instructions (install.json order)
        write_listed(h, a, st, nw, what)
    for a, st, nw, what in ut_hooks:
        write_listed(h, a, st, nw, what, cached_only=True)
    write_listed(h, ut["count"], ut["nstock"], ut["n"], "UTILITY row count", cached_only=True)
    log("rgb-full installed: overview + centre + strip + UTILITY row (reboot = stock)")


def br_any(h, addr, n):
    if read_ok(addr, n):
        return raw_br(h, addr, n)
    return br(h, addr, n)


def read_any(h, addr, n):
    out = bytearray()
    while len(out) < n:
        k = min(40, n - len(out))
        out += br_any(h, addr + len(out), k)
    return bytes(out)


def phasemeter(h, go):
    """phase meter (phasemeter_mk1.install_steps order): module with pm_prev = the
    live flush hook (must be stock), its state zeroed with pm_mode = 1, the zero flag
    words at the end of its area, then the flush-hook slot -> module (LAST)"""
    import phasemeter_mk1 as PM
    img, s = PM.build()
    img = bytearray(img)
    base, end = PM.BASE, (s["end"] + 3) & ~3
    state = bytearray(end - base - len(img))
    state[s["pm_mode"] - base - len(img)] = 1
    flags = (PM.FLAGS, bytes(PM.END_MAX - PM.FLAGS))
    print("plan (phase meter, %s):" % ("INSTALL" if go else "dry run, nothing written"))
    print("  block  %#010x +%#06x  pm module (code: cached + RAM)" % (base, len(img)))
    print("  block  %#010x +%#06x  pm state zeroed, pm_mode %#x = 1 (cached)" % (base + len(img), len(state), s["pm_mode"]))
    print("  block  %#010x +%#06x  zero flag words (cached)" % flags[0:1] + (len(flags[1]),) if False else
          "  block  %#010x +%#06x  zero flag words (cached)" % (flags[0], len(flags[1])))
    print("  hook   %#010x  %#010x -> %#010x  display-flush slot (LAST)" % (PM.HOOK, PM.HOOK_STOCK, base))
    cur = rd32(h, PM.HOOK)
    print("deck: flush slot %#010x = %#010x (%s)" % (PM.HOOK, cur, "stock" if cur == PM.HOOK_STOCK
          else "already the meter" if cur == base else "UNEXPECTED"))
    try:
        cnt = struct.unpack("<I", raw_br(h, int(MODEL["utility_table"]["count"], 16), 4))[0]
        print("deck: UTILITY row count %d (%s)" % (cnt, "WAVEFORM COLOR + PHASE METER rows installed"
              if cnt == 18 else "stock: no PHASE METER row to toggle it, the meter stays ON"))
    except IOError:
        pass
    if cur != PM.HOOK_STOCK:
        raise SystemExit("deck_write: flush slot not stock; nothing written")
    if not go:
        print("dry run only: rerun with --go to install")
        return
    struct.pack_into("<I", img, s["pm_prev"] - base, PM.HOOK_STOCK)
    write_block(h, base, img, "pm module")
    write_block(h, base + len(img), state, "pm state + pm_mode", cached_only=True)
    write_block(h, flags[0], flags[1], "pm zero flags", cached_only=True)
    write_listed(h, PM.HOOK, PM.HOOK_STOCK, base, "display-flush slot -> phase meter")
    log("phasemeter installed (reboot = stock)")


LDR_STATUS = ["IDLE", "RUN", "OK", "NOFILE", "TOOBIG", "BADHDR", "BADCRC", "BADOP", "NOTSTOCK", "MIDWAY"]


def loader_status(h):
    """read-only: the loader's state struct and its pool word"""
    import loader_mk1 as LD
    pool = rd32(h, LD.POOL)
    st = struct.unpack("<11I", read_block(h, LD.STATE, 44))
    print("deck: path_build pool %#010x = %#010x (%s)" % (LD.POOL, pool, "stock" if pool == LD.POOL_STOCK
          else "LOADER" if LD.BASE <= pool < LD.END_MAX else "UNEXPECTED"))
    if st[0] != 0x5453444C:
        print("deck: loader state not initialised (no stick mount seen since the loader went in)")
        return st
    name = LDR_STATUS[st[2]] if st[2] < len(LDR_STATUS) else hex(st[2])
    print("deck: loader status %s, done %s, mounts %d, attempts %d, file %d B, ops %d, "
          "bad addr %#x got %#x want %#x" % (name, st[1] == 0x454E4F44, st[3], st[4], st[5], st[6],
                                            st[7], st[8], st[9]))
    return st


def pm_status(h):
    """read-only: phase meter counters (syms of work/pm/build = the stick's pm.bin), the
    ANLZ context's beat grid header, the firmware's master number and its slot"""
    import loader_mk1 as LD
    pmb = os.path.join(ROOT, "work", "pm", "build")
    if open(os.path.join(pmb, "pm.bin"), "rb").read() != open(os.path.join(LD.SNAP, "bin", "pm.bin"), "rb").read():
        raise SystemExit("deck_write: work/pm/build/pm.bin is not the stick's pm.bin; syms would be wrong")
    ps = {l.split()[1]: int(l.split()[0], 16) for l in open(os.path.join(pmb, "pm.syms")) if l.strip()}
    print("deck: flush hook 0x08c37f14 = %#010x" % rd32(h, 0x08C37F14))
    for k in ("pm_mode", "pm_draws", "pm_src", "pm_n", "pm_rejects", "pm_visfail", "pm_stripped", "pm_nmiss",
              "pm_lm_n", "pm_lm_hits", "pm_dy"):
        v = rd32(h, ps[k])
        print("  %-12s %d" % (k, v if k != "pm_mode" else v & 0xFF))
    E = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))
    E = E.get("entries", E)
    ctx = rd32(h, int(E["anlz_ctx_table"]["addr"], 16))
    print("  ANLZ ctx    %#010x" % ctx)
    if 0x08000000 <= ctx < 0x10000000:
        q = ctx + int(E["beat_grid"]["ctx_off"], 16)
        hdr = struct.unpack("<8I", read_block(h, q, 32))
        print("  PQTZ @%#x  tag %#010x (want %s) rec %d n %d ptr %#010x" % (q, hdr[0], E["beat_grid"]["tag"],
                                                                         hdr[4], hdr[5], hdr[6]))
    g = E["deck_grid"]
    t = struct.unpack("<7I", read_block(h, int(E["track_len_word"]["addr"], 16), 28))
    print("  deck grid   track len %d, valid %d, count %d, first beats: ms %d bib %d, ms %d"
          % (t[0], t[2], t[3], t[4], t[5], t[6]))
    lm = E["link_master"]
    n = rd32(h, int(lm["master_number"], 16)) & 0xFF
    print("  master player %d" % n)
    for k in range(1, 5):
        st = int(lm["slot_table"], 16) + k * int(lm["slot_stride"], 16) + int(lm["slot_status_off"], 16)
        b = read_block(h, st, 0x28)
        print("  slot %d: flags %#04x bpm %d bib %d" % (k, b[9], struct.unpack_from("<H", b, 0x10)[0],
                                                       struct.unpack_from("<H", b, 0x26)[0]))


def loader(h, go):
    """stick loader (loader_mk1.build): module (code: cached + RAM), state zeroed,
    then the mount check's path_build pool word -> loader entry (LAST)"""
    import loader_mk1 as LD
    img, s = LD.build()
    entry = s["ldr_path_build"]
    print("plan (stick loader, %s):" % ("INSTALL" if go else "dry run, nothing written"))
    print("  block  %#010x +%#06x  loader module (code: cached + RAM)" % (LD.BASE, len(img)))
    print("  block  %#010x +%#06x  loader state zeroed" % (LD.STATE, 44))
    print("  hook   %#010x  %#010x -> %#010x  mount-check path_build pool (LAST)" % (LD.POOL, LD.POOL_STOCK, entry))
    cur = rd32(h, LD.POOL)
    print("deck: pool %#010x = %#010x (%s)" % (LD.POOL, cur, "stock" if cur == LD.POOL_STOCK else "NOT stock"))
    if cur != LD.POOL_STOCK:
        raise SystemExit("deck_write: path_build pool not stock (loader already in? power-cycle); nothing written")
    if not go:
        print("dry run only: rerun with --go to install")
        return
    write_block(h, LD.BASE, img, "stick loader module")
    write_block(h, LD.STATE, bytes(44), "stick loader state")
    write_listed(h, LD.POOL, LD.POOL_STOCK, entry, "mount-check path_build pool -> stick loader")
    log("stick loader installed (reboot = stock); insert a stick with MODS.BIN")


def main(av):
    if not av or av[0] not in ("noop", "lw", "rgb-overview", "rgb-full", "phasemeter", "loader",
                                "loader-status", "pm-status"):
        print(__doc__)
        return 1
    if av[0] in ("noop", "lw"):
        addr = int(av[1], 16)
        if addr % 4 or not in_free(addr) or addr >= P2:
            raise SystemExit("deck_write: %#x is not an aligned word in the free range" % addr)
    if av[0] == "rgb-overview":
        rgb_overview_plan()                                  # fail before opening the deck
    if av[0] == "rgb-full":
        full_plan()
    h = D.open_deck()
    try:
        r = D.text(D.handshake(h))
        v = D.text(D.version(h)).strip()
        print("handshake %r, version %r" % (r.strip(), v), flush=True)
        if "1.13" not in v:
            raise SystemExit("deck_write: not an XDJ-1000 MK1 on v1.13, nothing written")
        if av[0] == "noop":
            write_word(h, addr, rd32(h, addr), "noop")
        elif av[0] == "lw":
            write_word(h, addr, int(av[2], 16), "lw")
        elif av[0] == "phasemeter":
            UT_READ_SET()
            phasemeter(h, "--go" in av)
        elif av[0] == "rgb-overview":
            rgb_overview(h, "--go" in av)
        elif av[0] == "loader":
            loader(h, "--go" in av)
        elif av[0] == "loader-status":
            loader_status(h)
        elif av[0] == "pm-status":
            pm_status(h)
        else:
            rgb_full(h, "--go" in av)
    finally:
        h.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
