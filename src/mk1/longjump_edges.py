#!/usr/bin/env python3
"""Edge cases for the long beat jump (emulator, data only), stock vs a preset.

Each case restores an edge state (work/emu/xdj1000/<state>.vm, made in
work/longjump/states/), applies the preset's table with CDJ_PPOKE at the
handler entry, taps one pad and compares REMAIN with the same state's
baseline (mk1/longjump_test.window). States:

  nearstart  ~8 s into the 90 s test track (REMAIN 82.05)
  nearend    REMAIN ~11.9 s
  loop       a 4-beat loop active (the BEAT JUMP row reads LOOP MOVE)
  slip       SLIP on (and: jump, then SLIP off)
  nogrid     the test track with no rekordbox analysis (no beat grid)

    usage: python3 mk1/longjump_edges.py [PRESET]   -> work/longjump/edges_<preset>.json
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import longjump_test as LT                                     # noqa: E402
import remain_ocr                                              # noqa: E402

STICKS = {"nogrid": "work/testusb/nogrid_usb.img"}
CASES = [  # (state, pad code, extra script after the tap)
    ("nearstart", 1, ""), ("nearstart", 3, ""), ("nearstart", 5, ""), ("nearstart", 6, ""),
    ("nearend", 2, ""), ("nearend", 4, ""), ("nearend", 6, ""), ("nearend", 5, ""),
    ("loop", 1, ""), ("loop", 2, ""), ("loop", 6, ""),
    ("slip", 2, ""), ("slip", 5, ""), ("slip", 5, "wait 1; tap 50 428 250"),
    ("nogrid", 1, ""), ("nogrid", 2, ""), ("nogrid", 6, ""),
]


def window(out, state, beats, code, extra):
    s = "wait 2"
    if code:
        x, y = LT.PADS[str(code)]
        s += "; tap %d %d 200" % (x, y)
    if extra:
        s += "; " + extra
    s += "; wait 3; shot %s" % out
    env = dict(os.environ, CDJ_PPOKE=LT.ppoke(beats))
    argv = [sys.executable, os.path.join(HERE, "emu.py"), "run", "xdj1000", state, "8", "-", "--script", s]
    if state in STICKS:
        argv += ["--stick", os.path.join(ROOT, STICKS[state])]
    subprocess.run(argv, check=True, env=env, stdout=subprocess.DEVNULL)
    return remain_ocr.read(out)


def main(av):
    preset = av[0] if av else "long"
    d = os.path.join(ROOT, "work", "longjump", "edges")
    os.makedirs(d, exist_ok=True)
    res = []
    bases = {}
    for name, beats in (("stock", LT.PRESETS["stock"]), (preset, LT.PRESETS[preset])):
        for state, code, extra in CASES:
            key = (name, state, extra != "")
            if (name, state) not in bases:
                bases[(name, state)] = window(f"{d}/{name}_{state}_base.png", state, beats, None, "")
            tag = f"{name}_{state}_code{code}" + ("_slipoff" if extra else "")
            got = window(f"{d}/{tag}.png", state, beats, code, extra)
            b = beats[(code - 1) // 2]
            rev = code % 2 == 1
            exp = (1 if rev else -1) * b * 60.0 / LT.BPM
            base = bases[(name, state)]
            jump = None if got is None or base is None else round(got - base, 3)
            r = dict(preset=name, state=state, pad=("<<" if rev else ">>") + str(b), code=code,
                     extra=extra, expected_s=round(exp, 3), jump_s=jump,
                     remain_base=base, remain=got)
            r["verdict"] = ("UNREAD" if jump is None else "JUMPED" if abs(jump - exp) <= 0.35
                            else "REFUSED" if abs(jump) <= 0.15 else "OTHER")
            res.append(r)
            print(f"{name:>6} {state:>9} {r['pad']:>5}{' +slip off' if extra else '':10} expected {exp:+7.3f} "
                  f"jump {('%+7.3f' % jump) if jump is not None else '  n/a '}  {r['verdict']}", flush=True)
    json.dump(res, open(os.path.join(ROOT, "work", "longjump", f"edges_{preset}.json"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
