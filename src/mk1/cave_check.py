#!/usr/bin/env python3
"""Cave check (MK1): is a candidate zero run in the image really unused?

The test upstream used for its own cave (junk-fill), per trace window of
mk1/trace_set.py: restore the window's saved state, fill each candidate run
with 0xA5 through the gdbstub, run the window's action, then read every run
back. A byte that is no longer 0xA5 was written by the firmware during the
window (a zero write included). Any run written to in any window is dropped.
The restored state itself is checked separately (the runs must still be all
zero after boot, load and PERFORM: see work/trace/xdj1000/cave/snap_*.bin).

    usage: [EMU_SLOT=1] python3 mk1/cave_check.py [window ...]
           -> work/trace/xdj1000/cave/result.json (merged with earlier windows)
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from trace_set import ZONES_MK1, SECS, T_ACT                  # noqa: E402

RUNS = {"r1": (0x0885F820, 0x33F58), "r2": (0x08EC80E0, 0x827B), "r3": (0x08E4AEF0, 0x7B2C)}
# CAVE_RUNS="name:addr:len,..." checks other regions (e.g. free RAM above the
# image) with the same windows; results then go to result_<CAVE_TAG>.json
if os.environ.get("CAVE_RUNS"):
    RUNS = {n: (int(a, 0), int(l, 0)) for n, a, l in
            (r.split(":") for r in os.environ["CAVE_RUNS"].split(","))}
EXTRA = {   # windows beyond trace_set's: a track reload is the busiest allocator
    "reload": ("main", "tap 50 278 200; wait 6; key 0x11:0x01:300; wait 5; key 0x11:0x01:300; "
                       "wait 5; key 0x11:0x01:300; wait 5; key 0x11:0x01:300; wait 8"),
}
PAT = 0xA5


def window(name, state, action, d):
    fill = "; ".join(f"fill {a:#x} {n:#x} {PAT:#x}" for a, n in RUNS.values())
    check = "; ".join(f"check {a:#x} {n:#x} {PAT:#x} {d}/{name}.{r}.txt" for r, (a, n) in RUNS.items())
    s = f"wait 0.3; {fill}; wait {T_ACT - 0.3}" + (f"; {action}" if action else "") + \
        f"; wait {SECS - T_ACT - 1.5}; {check}; shot {d}/{name}.png"
    subprocess.run([sys.executable, os.path.join(HERE, "emu.py"), "run", "xdj1000", state,
                    str(SECS + 2), "-", "--script", s], check=True, stdout=subprocess.DEVNULL)
    out = {}
    for r in RUNS:
        first = open(f"{d}/{name}.{r}.txt").readline().split()
        out[r] = int(first[0])
    return out


def main(names):
    d = os.path.join(ROOT, "work", "trace", "xdj1000", "cave")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "result%s.json" % ("_" + os.environ["CAVE_TAG"] if os.environ.get("CAVE_TAG") else ""))
    res = json.load(open(p))["per_window"] if os.path.exists(p) else {}
    zones = dict(ZONES_MK1, **EXTRA)
    for name in (names or zones):
        state, action, *env = zones[name]
        if env:                                      # e.g. a direct handler call
            os.environ.update(env[0])
        res[name] = window(name, state, action, d)
        for k in (env[0] if env else {}):
            os.environ.pop(k, None)
        print(name, res[name], flush=True)
        json.dump({"pattern": PAT, "per_window": res}, open(p, "w"), indent=1)
    written = {r: [w for w, v in res.items() if v[r]] for r in RUNS}
    summary = {r: {"addr": f"{a:#010x}", "len": n,
                   "windows": len(res), "written_in": written[r],
                   "verdict": "DROP" if written[r] else "keep (no write seen)"}
               for r, (a, n) in RUNS.items()}
    json.dump({"pattern": PAT, "per_window": res, "summary": summary,
               "note": "windows recorded before the QEMU 11 update (base1..bj_rev4 except base1) "
                       "are in the earlier log: all 0 writes"}, open(p, "w"), indent=1)
    for r, s in summary.items():
        print(r, s["addr"], hex(s["len"]), s["verdict"], s["written_in"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
