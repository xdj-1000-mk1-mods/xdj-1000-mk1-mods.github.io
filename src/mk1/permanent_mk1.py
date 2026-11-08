#!/usr/bin/env python3
"""Flash form of the RGB / 3-band waveform mod + the UTILITY rows (MK1 v1.13).

Upstream tools/permanent_build.py's method, MK1 addresses (models table
entries startup, utility_table, utility_module; work/rgb/build/install.json):
  * in-image words (RGB hooks, UTILITY table pools) are patched directly;
  * the UTILITY count is patched in the .data SOURCE (startup copies it to
    the 0x14xxxxxx RAM the firmware reads), so nothing touches 0x14 at run time;
  * everything outside the image (RGB caves + mode byte, UTILITY module,
    zeroed bss) rides on the end of the decoded image; a boot copier on
    startup's init-hook pool (0x080009e0, caches off, bank 1 already DMA-zeroed,
    after the .data copy) zero-fills/copies them, then TAIL-JUMPS to the stock
    function that pool held (MK1 has no empty hook there).
The PHASE METER row shows NOT INSTALLED (meter, key shift, BEAT JUMP swipe and
KEY SHIFT control stay RAM installs). Called by build_mk1.py's 'flash' mod.
"""
import json
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "tools"), HERE]
from shasm import assemble                                   # noqa: E402

E_ = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
BASE = 0x08000000
ST = E_["startup"]
POOL, STOCK_FN = int(ST["init_hook_pool"], 16), int(ST["init_hook_stock"], 16)
DSRC, DEND, DDST = (int(ST["data_copy"][k], 16) for k in ("src", "src_end", "dst"))
RGB_DIR = os.path.join(ROOT, "work", "rgb", "build")
TAIL_ALIGN = 32
MODE_DEFAULT = 1                                             # 0 BLUE, 1 RGB, 2 3-BAND

COPIER = """
copier:                     ; jobs {{dst, src (0 = zero-fill), words}}, dst 0 ends, then the stock fn
  mov.l @({table:#x},pc),r1
next:
  mov.l @r1+,r2
  tst r2,r2
  bt done
  mov.l @r1+,r3
  mov.l @r1+,r4
  tst r3,r3
  bt zero
copy:
  mov.l @r3+,r0
  mov.l r0,@r2
  add #4,r2
  dt r4
  bf copy
  bra next
  nop
zero:
  mov #0,r0
zl:
  mov.l r0,@r2
  add #4,r2
  dt r4
  bf zl
  bra next
  nop
done:
  mov.l @r1,r0              ; the function the pool held; pr still = startup's return
  jmp @r0
  nop
.pool
"""


class Img:
    """the decoded image + RAM outside it (regions zero-filled at boot, then bytes)"""

    def __init__(self, dec):
        self.dec, self.zero, self.ram = dec, [], {}            # ram: addr -> byte, later wins

    def inside(self, a, n=1):
        return BASE <= a and a + n <= BASE + len(self.dec)

    def r32(self, a):
        assert self.inside(a, 4), hex(a)
        return struct.unpack_from("<I", self.dec, a - BASE)[0]

    def write(self, a, b):
        if self.inside(a, len(b)):
            self.dec[a - BASE:a - BASE + len(b)] = b
        else:
            assert not any(BASE <= x < BASE + len(self.dec) for x in (a, a + len(b) - 1)), hex(a)
            for i, x in enumerate(b):
                self.ram[a + i] = x

    def zero_fill(self, a, n):
        assert not self.inside(a) and a % 4 == 0 and n % 4 == 0, (hex(a), n)
        self.zero.append((a, n))


def data_src(ram_addr):
    """RAM address in the .data copy -> its source address in the image"""
    a = ram_addr - DDST + DSRC
    assert DSRC <= a < DEND, hex(ram_addr)
    return a


def bake_rgb(m, mode, log):
    j = json.load(open(os.path.join(RGB_DIR, "install.json")))
    for z in j["zero_first"].values():
        m.zero_fill(int(z["addr"], 16), (z["len"] + 3) & ~3)
    for b in j["blobs"]:
        m.write(int(b["addr"], 16), open(os.path.join(RGB_DIR, b["file"]), "rb").read())
    m.write(int(j["mode_addr"], 16), bytes([mode]))
    for h in j["hooks"]:
        a, v, n = int(h["addr"], 16), int(h["value"], 16), h["size"]
        assert m.inside(a, n), h
        m.write(a, v.to_bytes(n, "little"))
    log("rgb: %d blobs, %d hooks, mode %d" % (len(j["blobs"]), len(j["hooks"]), mode))


def bake_utility(m, log):
    import utility_mk1 as UT
    tab, cnt = data_src(UT.TAB), data_src(UT.COUNT)
    assert tab == int(UT.UT["image_table"], 16), hex(tab)
    assert m.r32(cnt) == UT.NSTOCK, "UTILITY count not 16 in the .data source"
    stock = bytes(m.dec[tab - BASE:tab - BASE + UT.NSTOCK * UT.REC])
    img, s = UT.image(stock)
    end = (s["end"] + 3) & ~3
    m.zero_fill(UT.BASE, end - UT.BASE)
    m.write(UT.BASE, img)
    for p in UT.POOLS:
        assert m.r32(p) == UT.TAB, hex(p)
        m.write(p, struct.pack("<I", s["ut_tab"]))
    m.write(cnt, struct.pack("<I", UT.NSTOCK + UT.NOURS))
    log("utility: module %#x..%#x, 4 pools, count %#x (.data source of %#x) 16 -> %d"
        % (UT.BASE, end, cnt, UT.COUNT, UT.NSTOCK + UT.NOURS))


def boot_tail(m):
    """append copier + jobs + payloads; point the init-hook pool at the copier"""
    assert m.r32(POOL) == STOCK_FN, "init-hook pool is not stock"
    tail = BASE + ((len(m.dec) + TAIL_ALIGN - 1) & ~(TAIL_ALIGN - 1))
    jobs = [(a, 0, n // 4) for a, n in sorted(m.zero)]
    data = []                                                # word runs; gaps < 32 B filled with 0
    for a in sorted(m.ram):
        w = a & ~3
        if data and w - data[-1][1] <= 32:
            data[-1][1] = max(data[-1][1], w + 4)
        else:
            data.append([w, w + 4])
    data = [(a0, bytes(m.ram.get(x, 0) for x in range(a0, e))) for a0, e in data]
    code = assemble(COPIER.format(table=0x12345678))
    table = tail + ((len(code) + 15) & ~15)
    code = assemble(COPIER.format(table=table))
    assert table - tail >= len(code)
    at = table + 12 * (len(jobs) + len(data)) + 8
    blobs = bytearray()
    for a0, w in data:
        jobs.append((a0, at + len(blobs), len(w) // 4))
        blobs += w
    out = bytearray(code.ljust(table - tail, b"\0"))
    for j in jobs:
        out += struct.pack("<III", *j)
    out += struct.pack("<II", 0, STOCK_FN) + blobs
    m.dec += bytes(tail - BASE - len(m.dec)) + out
    m.dec[POOL - BASE:POOL - BASE + 4] = struct.pack("<I", tail)
    return tail, jobs, len(out)


def apply(dec, mode=MODE_DEFAULT, log=print):
    """patch the decoded image in place (it grows by the boot tail)"""
    m = Img(dec)
    bake_rgb(m, mode, log)
    bake_utility(m, log)
    tail, jobs, n = boot_tail(m)
    for d, s_, w in jobs:
        log("  copier job %#010x..%#010x %s" % (d, d + 4 * w, "zero" if not s_ else "from %#x" % s_))
    log("boot copier + %d jobs at %#x (+%d B), pool %#x -> copier -> %#x"
        % (len(jobs), tail, n, POOL, STOCK_FN))
    return dict(tail=tail, jobs=jobs, zero=sorted(m.zero))


def emu(img_path, stick=None, junk=None):
    """cold boot of a flash image in qemu: the deck's own startup runs the
    copier; then every copied byte, hook and the UTILITY table are checked,
    and UTILITY is opened for a screenshot (work/mk1build/shots/)"""
    import emu as E
    import utility_mk1 as UT
    model = "xdj1000"
    dec = open(img_path, "rb").read()
    stock = bytearray(open(os.path.join(ROOT, "work", "MAIN_mk1_113.img"), "rb").read())
    want = Img(bytearray(stock))                             # rebuild the expected RAM end state
    apply_log = []
    bake_rgb(want, MODE_DEFAULT, apply_log.append)
    bake_utility(want, apply_log.append)
    shots = os.path.join(ROOT, "work", "mk1build", "shots")
    os.makedirs(shots, exist_ok=True)
    stick = stick or os.path.join(ROOT, "work", "testusb", "3band_usb.img")
    p = E.start(model, kernel=img_path, stick=stick, paused=bool(junk))
    ok = True
    if junk:                                                 # deck-like RAM before the copier runs
        E.step(model, "load 0x9800000 %s" % os.path.abspath(junk))
        print("RAM home pre-filled from %s, then cont" % junk, flush=True)
        E.cmd(model, "cont")
    MODEW = int(E_["screen_mode_word"]["addr"], 16)

    def chk(label, good):
        print(("ok   " if good else "FAIL ") + label, flush=True)
        return bool(good)

    def u32(a):
        return struct.unpack("<I", E.peek(model, a, 4))[0]

    try:
        t0 = time.time()
        while time.time() - t0 < 300:
            if time.time() - t0 < 20:                        # mode word may be junk before the BSS fill
                time.sleep(2)
                continue
            try:
                if u32(MODEW) == 1:
                    break
            except Exception:
                pass
            time.sleep(2)
        ok &= chk("booted to the main screen in %.0f s (mode word %d)" % (time.time() - t0, u32(MODEW)),
                  u32(MODEW) == 1)
        time.sleep(5)
        ok &= chk("init-hook pool -> copier %#x" % u32(POOL), u32(POOL) == struct.unpack_from("<I", dec, POOL - BASE)[0])
        bad = [a for a in sorted(want.ram) if E.peek(model, a, 1)[0] != want.ram[a]]
        ok &= chk("copied RAM bytes: %d/%d as built%s" % (len(want.ram) - len(bad), len(want.ram),
                  "" if not bad else ", first bad %#x" % bad[0]), not bad)
        for a, n in want.zero:
            got = E.peek(model, a, n)
            nz = [i for i in range(n) if got[i] and (a + i) not in want.ram]
            ok &= chk("zeroed %#x +%#x: %d non-zero bytes outside the copied ones" % (a, n, len(nz)), not nz)
        img_diff = [a for a in range(BASE, BASE + len(stock), 4)
                    if stock[a - BASE:a - BASE + 4] != dec[a - BASE:a - BASE + 4]]
        hooks_ok = all(E.peek(model, a, 4) == dec[a - BASE:a - BASE + 4] for a in img_diff
                       if not DSRC <= a < DEND)
        ok &= chk("%d changed image words in RAM as built (.data source excluded)" % len(img_diff), hooks_ok)
        ok &= chk("UTILITY count (RAM %#x) = %d, pools -> module table" % (UT.COUNT, u32(UT.COUNT)),
                  u32(UT.COUNT) == UT.NSTOCK + UT.NOURS and all(u32(a) == u32(UT.POOLS[0]) for a in UT.POOLS)
                  and UT.BASE <= u32(UT.POOLS[0]) < UT.END_MAX)
        E.step(model, "tap 568 37 1500")                     # hold MENU = UTILITY
        time.sleep(2)
        E.step(model, "rot 20")
        time.sleep(1.5)
        E.shot(model, os.path.join(shots, "utility_end.png"))
        E.step(model, "rot -1")
        time.sleep(1.5)
        E.shot(model, os.path.join(shots, "utility_wave.png"))
        ok &= chk("mode byte %d (RGB) after opening UTILITY" % E.peek(model, int(json.load(open(
            os.path.join(RGB_DIR, "install.json")))["mode_addr"], 16), 1)[0], True)
        E.step(model, "tap 568 37 300")                      # leave UTILITY
        time.sleep(3)
        TRACK_LEN = int(E_["track_len_word"]["addr"], 16)
        for st in ("key 0x13:0x04:300", 12, "rot 1", 3, "rot 1", 3,  # USB, 2nd entry, load + play
                   "key 0x11:0x01:300", 12, "key 0x11:0x01:300", 15):
            E.step(model, st) if isinstance(st, str) else time.sleep(st)
        E.shot(model, os.path.join(shots, "main_track.png"))
        ok &= chk("track loaded, main screen (len %d, mode %d), overview painted through the cave"
                  % (u32(TRACK_LEN), u32(MODEW)), u32(TRACK_LEN) != 0 and u32(MODEW) == 1)
        ok &= chk("deck running", "running" in E.cmd(model, "info status"))
    finally:
        try:
            E.cmd(model, "quit")
        except OSError:
            pass
        p.wait(timeout=60)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["emu"]:
        sys.exit(emu(sys.argv[2], junk=os.environ.get("MK1_JUNK")))
    print(__doc__)
