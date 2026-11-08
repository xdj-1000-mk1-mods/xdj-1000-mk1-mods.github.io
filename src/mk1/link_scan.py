#!/usr/bin/env python3
"""READ-ONLY: find the Pro DJ Link MASTER deck's beat state in this deck's RAM.

Regions = upstream's 700 link-state search areas (tools/link_beat_search.py:
0x0A8CF000 +0x4000, 0x0A8BE000 +0x2000) moved by +0x29FFFCC, the offset
that literals in mapped 700/MK1 function pairs agree on for that area
(work/map_700_to_mk1.json). Several passes; lists bytes that stay in 1..4
and take 3+ values (beat-in-bar counters) and words that step up steadily
(beat counters), with this deck's play state for context.

    link_scan.py [PASSES]        -> work/link/scan_<t>.npz + summary
"""
import os
import struct
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import deck_read as D                                          # noqa: E402

OFF = 0x29FFFCC
REGIONS = [(0x0A8CF000 + OFF, 0x4000), (0x0A8BE000 + OFF, 0x2000)]
OWN_BIB = 0x0A8D01F6 + OFF                                     # this deck's beat-in-bar on the 700
PLAY_STATE = 0x0E0C4228


def main(av):
    n = int(av[0]) if av else 6
    out = os.path.join(os.path.dirname(HERE), "work", "link")
    os.makedirs(out, exist_ok=True)
    snaps = {r: [] for r in REGIONS}
    times = []
    h = D.open_deck()
    try:
        D.handshake(h)
        ps = struct.unpack("<I", D.br(h, PLAY_STATE, 4)[0])[0]
        print("this deck play_state %d (3 = playing)" % ps, flush=True)
        for k in range(n):
            times.append(time.time())
            for a, size in REGIONS:
                buf = bytearray()
                while len(buf) < size:
                    m = min(40, size - len(buf))
                    buf += D.br(h, a + len(buf), m)[0]
                snaps[(a, size)].append(bytes(buf))
            print("pass %d/%d  %.0f s" % (k + 1, n, time.time() - times[0]), flush=True)
    finally:
        h.close()
    np.savez(os.path.join(out, "scan_%d.npz" % int(times[0])),
             **{"r%x" % a: np.frombuffer(b"".join(s), np.uint8).reshape(n, -1) for (a, _), s in snaps.items()})
    for (a, size), s in snaps.items():
        m = np.frombuffer(b"".join(s), np.uint8).reshape(n, size)
        inr = ((m >= 1) & (m <= 4)).all(axis=0)
        nv = np.array([len(set(m[:, i])) for i in range(size)])
        cand = np.where(inr & (nv >= 3))[0]
        print("region %#010x: %d beat-in-bar candidates" % (a, len(cand)))
        for i in cand[:20]:
            print("  %#010x  %s%s" % (a + i, list(m[:, i]), "  <- 700's own-deck byte" if a + i == OWN_BIB else ""))
        w = m[:, : size // 4 * 4].copy().view("<u4")
        d = np.diff(w.astype(np.int64), axis=0)
        steady = np.where((d > 0).all(axis=0) & (d < 200).all(axis=0))[0]
        print("  steadily rising words: %s" % [("%#010x" % (a + 4 * i), list(w[:, i])) for i in steady[:10]])


if __name__ == "__main__":
    main(sys.argv[1:])
