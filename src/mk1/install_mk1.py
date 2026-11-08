#!/usr/bin/env python3
"""Install every MK1 mod into a running emulated deck, in a safe order.

Order (emulator; the deck installer must keep it):
  1. RGB / 3-band waveform (rgb_mk1.py)       own hooks (overview + centre)
  2. UTILITY rows (utility_mk1.py)            WAVEFORM COLOR, PHASE METER
  3. BEAT JUMP swipe + labels (bjswipe_mk1.py) touch hook
  6. KEY SHIFT control (ksui_mk1.py)          flush + touch hooks, chains both
  4/5. key shift (keyshift_mk1.py) and the phase meter (phasemeter_mk1.py),
       both on the display-flush hook. Key shift's installer is a ONE-SHOT
       that runs from that hook with NO track loaded and then hands the
       hook back to whatever it found there. Either order works, as long as
       nothing re-hooks the flush pool while the one-shot is pending (ksh.c
       gives up, status 3, if it is no longer the head of the chain when it
       runs). keyshift_mk1.install() only returns once the one-shot has
       reported and released the hook, so the next step is safe.
       Default: key shift first (the hook is stock again when the meter
       installs); ks_first=False installs the meter first (the test does:
       it is the case where key shift runs at the head of a chain).

    install_mk1.py emu      qemu test: fresh boot, install all (meter first,
                            then key shift), load + play, MT on, key +4;
                            PHASE METER row OFF / ON from UTILITY
"""
import json
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bjswipe_mk1 as BJ                                       # noqa: E402
import keyshift_mk1 as KS                                      # noqa: E402
import phasemeter_mk1 as PM                                    # noqa: E402
import rgb_mk1                                                 # noqa: E402
import utility_mk1 as UT                                       # noqa: E402


def install_all(E, model, ks_first=True, log=print):
    u32 = lambda a: struct.unpack("<I", E.peek(model, a, 4))[0]
    out = {}
    if os.environ.get("MK1_JUNK"):                 # deck-like RAM home (work/survey/ram_09800000.bin)
        E.step(model, "load 0x9800000 %s" % os.path.abspath(os.environ["MK1_JUNK"]))
        log("RAM home pre-filled from %s" % os.environ["MK1_JUNK"])
    for st in rgb_mk1.install_script(1).split("; "):
        E.step(model, st)
    log("rgb: installed (mode RGB)")
    out["ut"] = UT.install(E, model)
    log("utility rows: installed")
    bimg, bs = BJ.build()
    for st in BJ.install_steps(bs):
        E.step(model, st)
    out["bj"] = bs
    log("beat jump swipe: installed")
    pimg, ps = PM.build()
    out["pm"] = ps

    def pm():
        for st in PM.install_steps(ps, u32(PM.HOOK)):
            E.step(model, st)
        log("phase meter: installed (chains %#x)" % u32(ps["pm_prev"]))

    if not ks_first:
        pm()
    st, dbg = KS.install(E, model)                 # returns after the one-shot
    out["ks_status"] = st
    log("key shift: status %d, flush hook now %#x" % (st, u32(KS.HOOK)))
    if ks_first:
        pm()
    import ksui_mk1 as KU                          # flush + touch hooks: after the one-shot
    out["ksui"] = KU.install(E, model)
    log("key shift control (PERFORM > HOT CUE label): installed")
    return out


def emu():
    import emu as E
    model = "xdj1000"
    shots = os.path.join(ROOT, "work", "install", "shots")
    os.makedirs(shots, exist_ok=True)
    p = E.start(model)
    ok = True

    def chk(label, good):
        print(("ok   " if good else "FAIL ") + label, flush=True)
        return bool(good)

    u32 = lambda a: struct.unpack("<I", E.peek(model, a, 4))[0]
    u8 = lambda a: E.peek(model, a, 1)[0]

    def utility_pm(value, tag):
        """UTILITY: last row = PHASE METER; push, turn to value, push, leave"""
        E.step(model, "tap 568 37 1500")
        time.sleep(3)
        E.step(model, "rot 20")
        time.sleep(1.5)
        E.step(model, "key 0x11:0x01:300")
        time.sleep(1.5)
        E.step(model, "rot %d" % (1 if value else -1))
        time.sleep(1)
        E.shot(model, os.path.join(shots, "ut_%s.png" % tag))
        E.step(model, "key 0x11:0x01:300")
        time.sleep(2)
        E.step(model, "tap 568 37 300")
        time.sleep(3)

    try:
        time.sleep(50)
        ok &= chk("fresh boot, no track", u32(KS.TRACK_LEN) == 0 and u32(PM.HOOK) == PM.HOOK_STOCK)
        # meter FIRST: the case where key shift's one-shot runs at the head of a chain
        r = install_all(E, model, ks_first=False, log=lambda m: print("  " + m, flush=True))
        ps = r["pm"]
        ok &= chk("key shift installed with the meter already hooked (status %d)" % r["ks_status"],
                  r["ks_status"] == 1)
        ks = r["ksui"]                              # installed last: head of the flush chain
        ok &= chk("flush chain: KEY SHIFT control (%#x) -> meter (%#x)" % (u32(PM.HOOK), u32(ks["ksui_fprev"])),
                  u32(PM.HOOK) == ks["ksui_flush"] and u32(ks["ksui_fprev"]) == PM.BASE)
        ok &= chk("meter chains to stock (%#x)" % u32(ps["pm_prev"]), u32(ps["pm_prev"]) == PM.HOOK_STOCK)
        for st in ("key 0x13:0x04:300", 12, "rot 1", 3, "rot 1", 3,     # USB, 2nd entry, load + play
                   "key 0x11:0x01:300", 12, "key 0x11:0x01:300", 15):
            E.step(model, st) if isinstance(st, str) else time.sleep(st)
        ok &= chk("track loaded and on the main screen (mode %d)" % u32(PM.MODEW),
                  u32(KS.TRACK_LEN) != 0 and u32(PM.MODEW) == 1)
        if u8(KS.MTW) != 1:
            E.step(model, "key 0x15:0x10:300")
            time.sleep(2)
        E.step(model, "poke32 %#x %#x" % (KS.KEY_WORD, KS.key_word(4)))
        time.sleep(2)
        a = KS.ks_state(E, model)
        time.sleep(4)
        b = KS.ks_state(E, model)
        n, sh = b["calls"] - a["calls"], b["shifted"] - a["shifted"]
        ok &= chk("key shift +4 with the meter chained: k %.4f, %d of %d blocks shifted" % (b["k"], sh, n),
                  n > 1000 and sh == n and abs(b["k"] - 2 ** (4 / 12)) < 1e-3)
        E.step(model, "key 0x10:0x01:300")                       # pause for exact meter checks
        time.sleep(1.5)
        G = PM.grid(E, model)
        ok &= chk("meter on (pm_mode %d)" % u8(ps["pm_mode"]),
                  u8(ps["pm_mode"]) == 1 and PM.meter_ok(E, model, G, os.path.join(shots, "a_meter_on.png"), 0))
        utility_pm(0, "off")
        d0 = u32(ps["pm_draws"])
        time.sleep(2)
        f = os.path.join(shots, "b_meter_off.png")
        E.shot(model, f)
        ok &= chk("UTILITY > PHASE METER OFF: pm_mode %d, no drawing (%d -> %d), stock meter back" % (
            u8(ps["pm_mode"]), d0, u32(ps["pm_draws"])),
            u8(ps["pm_mode"]) == 0 and u32(ps["pm_draws"]) == d0 and PM.meter_gone(f, 0))
        utility_pm(1, "on")
        time.sleep(1)
        ok &= chk("UTILITY > PHASE METER ON: pm_mode %d" % u8(ps["pm_mode"]),
                  u8(ps["pm_mode"]) == 1 and PM.meter_ok(E, model, G, os.path.join(shots, "c_meter_on_again.png"), 0))
        ok &= chk("key word still +4, deck running", u32(KS.KEY_WORD) == KS.key_word(4)
                  and "running" in E.cmd(model, "info status"))
    finally:
        try:
            E.cmd(model, "quit")
        except OSError:
            pass
        p.wait(timeout=60)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["emu"]:
        sys.exit(emu())
    print(__doc__)
