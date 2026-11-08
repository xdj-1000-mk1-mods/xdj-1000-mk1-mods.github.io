#!/usr/bin/env python3
"""READ-ONLY survey of a deck RAM range (STATUS step 2: the mods' home).

Reads [A, A+N) with deck_read.br (40 B per read, deck_read's allow-list and
range guard apply) into work/survey/ram_<A>.bin; progress is checkpointed
every 64 KB, so a re-run resumes. Then prints the non-zero 4 KB pages as runs.

    deck_survey.py 09800000 200000      read + summary
    deck_survey.py 09800000 200000 -s   summary of what is on disk only
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import deck_read as D                                          # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "work", "survey")
CHUNK, CKPT, PAGE = 40, 0x10000, 0x1000


def read(a0, n, path):
    done = path + ".done"
    have = int(open(done).read()) if os.path.exists(done) else 0
    buf = bytearray(open(path, "rb").read()[:have]) if have else bytearray()
    t0, fails = time.time(), 0
    while len(buf) < n:
        h = D.open_deck()
        try:
            D.handshake(h)
            while len(buf) < n:
                k = min(CHUNK, n - len(buf))
                buf += D.br(h, a0 + len(buf), k)[0]
                if len(buf) % CKPT == 0 or len(buf) == n:
                    open(path, "wb").write(buf)
                    open(done, "w").write(str(len(buf)))
                    r = (len(buf) - have) / max(time.time() - t0, 1e-3)
                    print("%#x  %d/%d  %.0f B/s  eta %.0f min" % (a0 + len(buf), len(buf), n, r,
                          (n - len(buf)) / max(r, 1) / 60), flush=True)
        except IOError as e:
            fails += 1
            print("retry %d after: %s" % (fails, e), flush=True)
            buf = buf[:len(buf) - len(buf) % CKPT]             # back to the last checkpoint
            if fails > 5:
                raise SystemExit("deck_survey: too many failed reads, stopping")
        finally:
            h.close()
    return bytes(buf)


def summary(a0, b):
    pages = [i for i in range(0, len(b), PAGE) if any(b[i:i + PAGE])]
    runs = []
    for i in pages:
        if runs and runs[-1][1] == i:
            runs[-1][1] = i + PAGE
        else:
            runs.append([i, i + PAGE])
    nz = sum(1 for x in b if x)
    print("%#x +%#x: %d non-zero bytes, %d/%d non-zero 4 KB pages, %d runs"
          % (a0, len(b), nz, len(pages), len(b) // PAGE, len(runs)))
    for s, e in runs[:40]:
        seg = b[s:e]
        print("  %#010x-%#010x  %6d KB  %5.1f%% non-zero  first %s" % (
            a0 + s, a0 + e, (e - s) // 1024, 100.0 * sum(1 for x in seg if x) / len(seg),
            seg[next(j for j in range(len(seg)) if seg[j]):][:16].hex(" ")))
    if len(runs) > 40:
        print("  ... %d more runs" % (len(runs) - 40))


def main(av):
    if len(av) < 2:
        print(__doc__)
        return 1
    a0, n = int(av[0], 16), int(av[1], 16)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "ram_%08x.bin" % a0)
    b = open(path, "rb").read()[:n] if "-s" in av else read(a0, n, path)
    summary(a0, b)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
