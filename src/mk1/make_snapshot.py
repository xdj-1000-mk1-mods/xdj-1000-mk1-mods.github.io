#!/usr/bin/env python3
"""Save a self-contained, runnable copy of the current MK1 deck mods.

    make_snapshot.py [NAME]   -> mk1/snapshots/<NAME or today>/

Contents: install.py (from snapshot_install.py), deck_read.py, bundle.json
(every address, stock value and order, precomputed from the model table and
the unpacked v1.13 image so the snapshot needs no firmware), bin/ (built mod
binaries: our code only), README.md, SHA256SUMS. The plan is the same one
deck_write.py's rgb-full and phasemeter install (checked here, field by field).
"""
import hashlib
import json
import os
import shutil
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def main(av):
    import deck_write as W
    import phasemeter_mk1 as PM
    name = av[0] if av else time.strftime("%Y-%m-%d")
    out = name if os.sep in name else os.path.join(HERE, "snapshots", name)
    if os.path.exists(out):
        raise SystemExit("make_snapshot: %s exists" % out)
    os.makedirs(os.path.join(out, "bin"))
    blocks, zeros, (mode, mval), hooks, ut, ut_hooks = W.full_plan()
    pimg, ps = PM.build()
    pimg = bytearray(pimg)
    struct.pack_into("<I", pimg, ps["pm_prev"] - PM.BASE, PM.HOOK_STOCK)
    hx = lambda v: "%#010x" % v
    files = {}
    for a, b, f in blocks:
        files[f] = b
    ub = bytes(ut["img"]) + bytes(ut["end"] - ut["base"] - len(ut["img"]))
    files["ut.bin"] = ub
    files["pm.bin"] = bytes(pimg)
    pend = (ps["end"] + 3) & ~3
    bundle = {
        "what": "XDJ-1000 MK1 v1.13 RAM mods: RGB/3-band waveforms, UTILITY WAVEFORM COLOR + PHASE METER rows, "
                "phase meter with linked-master row",
        "made": time.strftime("%Y-%m-%d %H:%M"),
        "free": [hx(W.FREE[0]), hx(W.FREE[1])],
        "track_len": W.MODEL["track_len_word"]["addr"],
        "rgb": {
            "blocks": [{"addr": hx(a), "file": f} for a, b, f in blocks],
            "zeros": [{"addr": hx(a), "len": n, "what": k} for a, n, k in zeros],
            "mode": [hx(mode), hx(mval)],
            "hooks": [{"addr": hx(a), "stock": hx(st), "new": hx(nw), "what": w} for a, st, nw, w in hooks],
        },
        "utility": {"base": hx(ut["base"]), "file": "ut.bin", "tab": hx(ut["tab"]),
                    "stock_tab": hx(ut["stock_tab"]), "nstock": ut["nstock"], "rec": ut["rec"],
                    "count": hx(ut["count"]), "n": ut["n"], "pools": [hx(a) for a, st, nw, w in ut_hooks]},
        "phasemeter": {"base": hx(PM.BASE), "file": "pm.bin", "state_addr": hx(PM.BASE + len(pimg)),
                       "state_len": pend - PM.BASE - len(pimg), "pm_mode": hx(ps["pm_mode"]),
                       "flags_addr": hx(PM.FLAGS), "flags_len": PM.END_MAX - PM.FLAGS,
                       "hook": hx(PM.HOOK), "stock": hx(PM.HOOK_STOCK)},
    }
    for f, b in files.items():
        open(os.path.join(out, "bin", f), "wb").write(b)
    json.dump(bundle, open(os.path.join(out, "bundle.json"), "w"), indent=1)
    shutil.copy(os.path.join(HERE, "snapshot_install.py"), os.path.join(out, "install.py"))
    shutil.copy(os.path.join(HERE, "deck_read.py"), os.path.join(out, "deck_read.py"))
    open(os.path.join(out, "README.md"), "w").write(README % dict(made=bundle["made"]))
    sums = []
    for dp, _, fs in os.walk(out):
        for f in sorted(fs):
            p = os.path.join(dp, f)
            sums.append("%s  %s" % (hashlib.sha256(open(p, "rb").read()).hexdigest(), os.path.relpath(p, out)))
    open(os.path.join(out, "SHA256SUMS"), "w").write("\n".join(sorted(sums, key=lambda s: s[66:])) + "\n")
    print("snapshot:", out)
    return out


README = """# XDJ-1000 MK1 mods: snapshot %(made)s

Runnable copy of the mods as installed and confirmed on a real XDJ-1000 MK1
(firmware 1.13) on 2026-11-01. **RAM only**: nothing is flashed, a power cycle
returns the deck to stock. No firmware is included.

## What it installs
- RGB waveform colours on the overview, the centre waveform and the PERFORM
  strip; UTILITY > WAVEFORM COLOR: BLUE / RGB / 3-BAND (3-BAND needs PWV6/PWV7
  in the stick's .EXT files, see tools/make_3band.py in xdj-mod-studio).
- Phase meter: blue row = this deck, orange row = the linked master (tested
  with 2 decks; this deck as master mirrors its own beats). UTILITY > PHASE
  METER: ON / OFF.

## Needs
Python 3, `pip install hid` (and the hidapi library, e.g. `brew install hidapi`),
the deck on its rear USB-B port.

## Use
1. Power-cycle the deck. Do **not** load a track.
2. `python3 install.py check`        (read-only)
3. `python3 install.py all --go`     (about 3 minutes)
4. Load a track.

Writes are logged to `deck_writes.log`. To reinstall, power-cycle first: never
install over a running copy. Files: install.py (installer), deck_read.py (USB
shell client), bundle.json (addresses, stock values, order), bin/ (mod code),
SHA256SUMS.
"""

if __name__ == "__main__":
    main(sys.argv[1:])
