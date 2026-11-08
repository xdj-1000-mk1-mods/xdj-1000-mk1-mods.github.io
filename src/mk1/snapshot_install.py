#!/usr/bin/env python3
"""install.py -- put the XDJ-1000 MK1 (v1.13) mods into a connected deck's RAM.

Self-contained snapshot installer: needs only Python 3, `pip install hid`
(+ the hidapi library) and the files next to it (deck_read.py, bundle.json,
bin/). RAM only, never flash: a power cycle returns the deck to stock.

    install.py check              read-only: what would be written, deck state
    install.py rgb --go           RGB / 3-band waveforms (overview, centre, PERFORM
                                  strip) + UTILITY rows WAVEFORM COLOR / PHASE METER.
                                  Only right after a power cycle with NO track loaded.
    install.py phasemeter --go    phase meter (own row + linked-master row)
    install.py all --go           rgb, then phasemeter

Gates (checked before anything is sent): the deck must answer v1.13; blocks
only inside 0x09800000-0x09A00000 (read-only survey of a real deck: unused);
hook words only from bundle.json and only if the deck holds their stock
value; every write is read back (blocks through the cached address AND the
uncached alias), anything unexpected stops the run; hooks go last.
Every write is logged to deck_writes.log next to this file.
"""
import json
import os
import re
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import deck_read as D                                          # noqa: E402

B = json.load(open(os.path.join(HERE, "bundle.json")))
H = lambda v: int(v, 16)
P2 = 0xA0000000
FREE = (H(B["free"][0]), H(B["free"][1]))
LOG = os.path.join(HERE, "deck_writes.log")
UT_READ = (H(B["utility"]["stock_tab"]), H(B["utility"]["count"]) + 4)


def blob(name):
    return open(os.path.join(HERE, "bin", name), "rb").read()


def in_free(a, n=4):
    a0 = a & ~P2 if a >= P2 else a
    return FREE[0] <= a0 and a0 + n <= FREE[1] and (a < P2 or a - a0 == P2)


def _cmd(h, q):
    h.write(b"\x00" + (q + b"\x00").ljust(64, b"\x00"))


def _lw(h, addr, val):
    """the ONLY write this tool sends; callers have gated addr"""
    assert addr % 4 == 0
    _cmd(h, b"%x,%xLW\r" % (addr, val & 0xFFFFFFFF))
    return D._drain(h, 1.0, lambda o: b"\n" in o.replace(b"\x00", b""))


def raw_br(h, addr, n):
    _cmd(h, b"%x,%xBR\r" % (addr, n - 1))
    pat = re.compile(rb"\b[0-9A-Fa-f]{2}\b")

    def done(o):
        t = o.replace(b"\x00", b"")
        return len(pat.findall(t.split(b"BR")[-1])) >= n and (b"\n" in t or b"\r" in t)
    t = D._drain(h, 6.0, done).replace(b"\x00", b"")
    vals = pat.findall(t.split(b"BR")[-1]) if b"BR" in t else pat.findall(t)
    if len(vals) < n:
        raise IOError("short BR reply for %#x+%d" % (addr, n))
    return bytes(int(v, 16) for v in vals[-n:])


def br(h, addr, n):
    if UT_READ[0] <= addr and addr + n <= UT_READ[1]:
        return raw_br(h, addr, n)
    if addr >= P2:
        if not in_free(addr, n):
            raise SystemExit("install: read %#x outside the allowed range" % addr)
        return raw_br(h, addr, n)
    return D.br(h, addr, n)[0]


def rd32(h, addr):
    return struct.unpack("<I", br(h, addr, 4))[0]


def read_block(h, addr, n):
    out = bytearray()
    while len(out) < n:
        out += br(h, addr + len(out), min(40, n - len(out)))
    return bytes(out)


def log(line):
    open(LOG, "a").write(time.strftime("%Y-%m-%d %H:%M:%S  ") + line + "\n")
    print(line, flush=True)


def write_block(h, addr, data, tag, cached_only=False):
    data = bytes(data) + bytes(-len(data) % 4)
    if addr % 4 or not in_free(addr, len(data)):
        raise SystemExit("install: block %#x+%d outside the free range" % (addr, len(data)))
    for i in range(0, len(data), 4):
        v = struct.unpack_from("<I", data, i)[0]
        _lw(h, addr + i, v)
        if not cached_only:
            _lw(h, P2 | (addr + i), v)
    got0 = read_block(h, addr, len(data))
    got2 = got0 if cached_only else read_block(h, P2 | addr, len(data))
    ok = got0 == data and got2 == data
    log("%#010x +%#x  block %s  [%s]" % (addr, len(data), "OK" if ok else "MISMATCH", tag))
    if not ok:
        raise SystemExit("install: block read-back mismatch at %#x, stopping" % addr)


def write_listed(h, addr, stock, new, what, cached_only=False):
    old = rd32(h, addr)
    if old != stock:
        raise SystemExit("install: %#x holds %#x, not stock %#x: refusing [%s]" % (addr, old, stock, what))
    _lw(h, addr, new)
    if not cached_only:
        _lw(h, P2 | addr, new)
    got0 = rd32(h, addr)
    got2 = got0 if cached_only else struct.unpack("<I", raw_br(h, P2 | addr, 4))[0]
    ok = got0 == new and got2 == new
    log("%#010x  HOOK %#010x -> %#010x  %s  [%s]" % (addr, old, new, "OK" if ok else "MISMATCH", what))
    if not ok:
        raise SystemExit("install: read-back mismatch at %#x" % addr)


def rgb(h, go):
    R, U = B["rgb"], B["utility"]
    tl = rd32(h, H(B["track_len"]))
    hooks = [(H(x["addr"]), H(x["stock"]), H(x["new"]), x["what"]) for x in R["hooks"]]
    pools = [(H(p), H(U["stock_tab"]), H(U["tab"]), "UTILITY table pool") for p in U["pools"]]
    bad = [hex(a) for a, st, nw, w in hooks + pools if rd32(h, a) != st]
    cnt = rd32(h, H(U["count"]))
    print("rgb: track loaded %s; hook words not stock: %s; UTILITY count %d"
          % ("YES" if tl else "no", bad or "none", cnt))
    if tl:
        raise SystemExit("install: a track is loaded. Power-cycle, do NOT load a track, then rerun")
    if bad or cnt != U["nstock"]:
        raise SystemExit("install: deck not in the stock state; nothing written")
    if not go:
        return
    for x in R["blocks"]:
        write_block(h, H(x["addr"]), blob(x["file"]), x["file"])
    for x in R["zeros"]:
        write_block(h, H(x["addr"]), bytes(x["len"]), "zero " + x["what"])
    write_block(h, H(R["mode"][0]), struct.pack("<I", H(R["mode"][1])), "mode word = RGB")
    rows = read_block(h, H(U["stock_tab"]), U["nstock"] * U["rec"])     # the deck's own 16 rows
    ub = bytearray(blob(U["file"]))
    off = H(U["tab"]) - H(U["base"])
    ub[off:off + len(rows)] = rows
    write_block(h, H(U["base"]), ub, "UTILITY module + deck rows")
    for a, st, nw, w in hooks:
        write_listed(h, a, st, nw, w)
    for a, st, nw, w in pools:
        write_listed(h, a, st, nw, w, cached_only=True)
    write_listed(h, H(U["count"]), U["nstock"], U["n"], "UTILITY row count", cached_only=True)
    log("rgb + UTILITY rows installed (reboot = stock)")


def phasemeter(h, go):
    P = B["phasemeter"]
    cur = rd32(h, H(P["hook"]))
    print("phasemeter: flush slot %#x = %#x (%s)" % (H(P["hook"]), cur,
          "stock" if cur == H(P["stock"]) else "NOT stock"))
    if cur != H(P["stock"]):
        raise SystemExit("install: flush slot not stock; nothing written")
    if not go:
        return
    write_block(h, H(P["base"]), blob(P["file"]), "pm module")
    st = bytearray(P["state_len"])
    st[H(P["pm_mode"]) - H(P["state_addr"])] = 1
    write_block(h, H(P["state_addr"]), st, "pm state + pm_mode", cached_only=True)
    write_block(h, H(P["flags_addr"]), bytes(P["flags_len"]), "pm zero flags", cached_only=True)
    write_listed(h, H(P["hook"]), H(P["stock"]), H(P["base"]), "display-flush slot -> phase meter")
    log("phase meter installed (reboot = stock)")


def main(av):
    if not av or av[0] not in ("check", "rgb", "phasemeter", "all"):
        print(__doc__)
        return 1
    go = "--go" in av and av[0] != "check"
    h = D.open_deck()
    try:
        D.handshake(h)
        v = D.text(D.version(h)).strip()
        print("deck version %r" % v)
        if "1.13" not in v:
            raise SystemExit("install: not an XDJ-1000 MK1 on v1.13, nothing written")
        if av[0] in ("check", "rgb", "all"):
            rgb(h, go)
        if av[0] in ("check", "phasemeter", "all"):
            if av[0] == "all" and go:
                pass                                        # the rgb step left the flush slot stock
            phasemeter(h, go)
        if not go:
            print("read-only check done; nothing written (add --go to install)")
    finally:
        h.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
