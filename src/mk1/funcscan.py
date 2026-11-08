#!/usr/bin/env python3
"""Find functions in an unpacked SH-4 LE image (base 0x08000000) without Ghidra.

Fallback for the Ghidra headless export. Decoding semantics follow
tools/shxray.py (branch_target, pool_target, walk) but run on an image passed
in, not shxray's module-level /tmp/dec4.bin.

Entry points:
  1. the image entry (0x08000000, 0x08000800) and prologue starts, then the
     closure of their calls: bsr and pool-loaded jsr/jmp targets found in
     walked code only (a linear sweep picks up data that decodes as bsr)
  2. prologues: a run of `mov.l Rm,@-r15` pushes ending in `sts.l pr,@-r15`,
     accepted only where the previous code ends (rts + delay slot, nop
     padding, or a literal pool)
Each entry is walked by recursive descent (bt/bf/bra followed; bsr/jsr are
calls; rts/jmp end a path). Per function the JSON holds start, size, insn
count, ordered call targets, referenced strings (ASCII or UTF-16LE, via pool
literals), its literal-pool loads [slot, value] and a signature hash of the walked instructions with call
displacements and pool values masked out.

    usage: python3 mk1/funcscan.py IMAGE OUT.json [--name NAME]
"""
import hashlib
import json
import re
import struct
import sys
import time

BASE = 0x08000000
PUSH = 0x2F06          # mov.l Rm,@-r15  (2Fm6)
STS_PR = 0x4F22        # sts.l pr,@-r15
RTS = 0x000B
NOP = 0x0009
MIN_STR = 4


def u16s(img):
    n = len(img) // 2
    return struct.unpack_from(f"<{n}H", img, 0)


def disp12(w):
    d = w & 0xFFF
    return d - 0x1000 if d & 0x800 else d


def disp8(w):
    d = w & 0xFF
    return d - 0x100 if d & 0x80 else d


def pool_addr(pc, w):
    """mov.l @(disp,PC),Rn -> (n, pool address)"""
    return (w >> 8) & 0xF, ((pc + 4) & ~3) + (w & 0xFF) * 4


class Image:
    def __init__(self, img):
        self.img = img
        self.w = u16s(img)
        self.end = BASE + len(img)

    def h(self, pc):
        i = (pc - BASE) >> 1
        return self.w[i] if 0 <= i < len(self.w) else None

    def u32(self, a):
        o = a - BASE
        return struct.unpack_from("<I", self.img, o)[0] if 0 <= o <= len(self.img) - 4 else None

    def in_code(self, a):
        return BASE <= a < self.end and not a & 1

    def string_at(self, a):
        o = a - BASE
        if not (0 <= o < len(self.img)):
            return None
        m = re.match(rb"[\x20-\x7e\t\r\n]{%d,200}\x00" % MIN_STR, self.img[o:o + 202])
        if m:
            return m.group()[:-1].decode("ascii")
        m = re.match(rb"(?:[\x20-\x7e]\x00){%d,200}\x00\x00" % MIN_STR, self.img[o:o + 404])
        if m and not o & 1:
            return "u:" + m.group()[:-2].decode("utf-16le")
        return None


def scan_pools(im):
    """Every PC-relative mov.l: pool address -> loading pc (pools are data)."""
    pools = {}
    w = im.w
    for i, x in enumerate(w):
        if x >> 12 == 0xD:
            pc = BASE + 2 * i
            _, pa = pool_addr(pc, x)
            if BASE <= pa < im.end:
                pools.setdefault(pa, pc)
    return pools


def prologue_seeds(im, pools):
    """Starts of `[mov.l Rm,@-r15]* sts.l pr,@-r15` runs that sit right after
    the end of other code (rts + delay slot, nop padding, or a pool)."""
    w = im.w
    out = set()
    for i, x in enumerate(w):
        if x != STS_PR:
            continue
        j = i
        while j > 0 and (w[j - 1] & 0xFF0F) == PUSH:
            j -= 1
        prev = BASE + 2 * j - 2
        if (j >= 2 and w[j - 2] == RTS) or (j >= 1 and w[j - 1] == NOP) \
                or prev in pools or (prev - 2) in pools:
            out.add(BASE + 2 * j)
    return out


def walk(im, entry, pools, limit=6000):
    code, calls, strs, lits = [], [], [], []
    stack, seen = [entry], set()
    while stack and len(seen) < limit:
        pc = stack.pop()
        while pc not in seen and len(seen) < limit:
            x = im.h(pc)
            if x is None or pc in pools:
                break
            seen.add(pc)
            top = x >> 12
            if top == 0xD:
                n, pa = pool_addr(pc, x)
                v = im.u32(pa)
                if v is not None:
                    lits.append((pc, n, v, pa))
                    s = im.string_at(v & 0x1FFFFFFF if v >> 29 in (4, 5) else v)
                    if s:
                        strs.append(s)
            if top == 0xB:                                   # bsr: call
                calls.append((pc, pc + 4 + disp12(x) * 2))
                pc += 2
                continue
            if top == 0xA:                                   # bra
                seen.add(pc + 2)                             # delay slot
                pc = pc + 4 + disp12(x) * 2
                continue
            if top == 0x8 and (x >> 8) & 0xF in (0x9, 0xB, 0xD, 0xF):   # bt/bf(/s)
                stack.append(pc + 4 + disp8(x) * 2)
                pc += 2
                continue
            if (x & 0xF0FF) in (0x400B, 0x402B):            # jsr / jmp @Rn
                n = (x >> 8) & 0xF
                tgt = next((v for p, r, v, _ in reversed(lits) if r == n and pc - p <= 16), None)
                if tgt is not None:
                    tgt &= 0x1FFFFFFF if tgt >> 29 in (4, 5) else 0xFFFFFFFF
                    calls.append((pc, tgt if im.in_code(tgt) else None))
                else:
                    calls.append((pc, None))
                if x & 0xF0FF == 0x402B:                     # jmp: tail, path ends
                    seen.add(pc + 2)
                    break
                pc += 2
                continue
            if x == RTS or (x & 0xF0FF) in (0x0023,):      # rts / braf
                seen.add(pc + 2)
                break
            pc += 2
    return seen, calls, strs, lits


def signature(im, seen, pools):
    """Walked instructions in address order, with call/pool data masked:
    bsr disp12 masked (callee moves independently); pool *values* never
    enter the hash (pools are not instructions); everything else kept."""
    out = []
    for pc in sorted(seen):
        if pc in pools:
            continue
        x = im.h(pc)
        if x is None:
            continue
        if x >> 12 == 0xB:
            x = 0xB000
        out.append(x)
    return hashlib.sha1(struct.pack(f"<{len(out)}H", *out)).hexdigest()[:20], len(out)


def scan(path, name):
    t0 = time.time()
    im = Image(open(path, "rb").read())
    pools = scan_pools(im)
    prologues = prologue_seeds(im, pools)
    # closure: callees only come from code we have actually walked, so data
    # that happens to decode as bsr (any 0xBxxx halfword) adds nothing
    queue = sorted(prologues | {BASE, BASE + 0x800})
    calls, done, walked = set(), set(), {}
    while queue:
        e = queue.pop()
        if e in done:
            continue
        done.add(e)
        r = walk(im, e, pools)
        if not r[0]:
            continue
        walked[e] = r
        for _, t in r[1]:
            if t is not None and im.in_code(t) and t not in done:
                calls.add(t)
                queue.append(t)
    funcs = {}
    for e, (seen, cl, strs, lits) in walked.items():
        sig, n = signature(im, seen, pools)
        funcs[e] = {
            "addr": f"{e:#010x}",
            "size": max(seen) + 2 - e if max(seen) >= e else 2,
            "insns": n,
            "seed": ("call" if e in calls else "") + ("+prologue" if e in prologues else ""),
            "calls": [f"{t:#010x}" if t is not None else None for _, t in sorted(cl)],
            "strings": sorted(set(strs)),
            "sig": sig,
            # literal pool loads in address order: [pool slot, value]
            "lits": [[f"{pa:#010x}", f"{v:#010x}"] for _, _, v, pa in sorted(lits)],
        }
    out = {"image": path, "name": name, "base": f"{BASE:#010x}", "size": len(im.img),
           "sha256": hashlib.sha256(im.img).hexdigest(),
           "backend": "capstone-free recursive descent (mk1/funcscan.py)",
           "counts": {"functions": len(funcs), "call_seeds": len(calls),
                      "prologue_seeds": len(prologues), "pools": len(pools)},
           "functions": [funcs[k] for k in sorted(funcs)]}
    print(f"{name}: {len(funcs)} functions ({len(calls)} call seeds, "
          f"{len(prologues)} prologue seeds) in {time.time() - t0:.0f}s")
    return out


def main():
    img, out = sys.argv[1], sys.argv[2]
    name = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else img
    json.dump(scan(img, name), open(out, "w"))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
