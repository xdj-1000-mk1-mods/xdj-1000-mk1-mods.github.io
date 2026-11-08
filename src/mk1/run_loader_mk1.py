#!/usr/bin/env python3
"""Run the XDJ-1000 (MK1) loader in the SH-4 emulator and let it unpack MAIN.

Based on tools/run1000loader.py (MK2). The deck unpacks its own firmware:
flash S-records -> RAM 0x08000000. Permissive bus (unknown devices read 0,
writes ignored). When the PC enters RAM the loader is done; the written RAM
is dumped and compared byte for byte with work/MAIN_mk1_113.img.

Changes from the MK2 script:
  - flash comes from the UPD's MAIN section (decimal manifest), and each S2
    record writes exactly ln-4 bytes (the MK2 script's rec[4:ln-1] wrote
    one byte short and shifted the rest of the buffer)
  - the two boot-time workarounds match by behaviour, not MK2 addresses
    (MK1's boot code is shifted; its delay loop is not at 0x134):
      odd jump target  -> clear bit 0
      `dt Rn; bf -2` delay loop with a huge Rn -> set Rn to 1
  - RAM follows emu/machine.py: two 64 MB banks at 0x08000000 and 0x0C000000,
    mirrored at 0x10000000-0x17FFFFFF. MK1's boot RAM test (flash 0x4C4-0x6DC)
    writes/reads 0x55../0xAA.. at every 32 MB step of P2 0xA8000000-0xB7FFFFFF
    and on a mismatch blinks GPIO PADR 0xA4050100 forever (loop 0x700-0x762)
  - only the image range is dumped (the stack lives in the bank1 mirror)
  - minimal DMAC0 (0xFE008000): MK1's loader memcpy (flash 0x772) moves
    >=16-byte blocks with DMA ch5 (CHCR 0x5438) and polls CHCR.TE; transfers
    run on DE with DMAOR.DME set, then TCR=0 and TE, as in emu/sh7724.py
  - emu.sh4 run() returns a string on PcHalt (it does not re-raise), so the
    run loop checks the return value
  - no hard-coded hash; the oracle is the unpacker's output

    usage: python3 mk1/run_loader_mk1.py [UPD] [IMG]     (from xdj-mod-studio/)
"""
import hashlib
import json
import struct
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from emu.sh4 import SH4, PcHalt

UPD = os.path.join(ROOT, "..", "..", "FW", "XDJ1000", "XDJ1000.UPD")
IMG = os.path.join(ROOT, "work", "MAIN_mk1_113.img")
MANIFEST = os.path.join(HERE, "manifest.json")
FLASH_SIZE = 0xB00000
RAM_SIZE = 128 * 1024 * 1024                 # bank0 + bank1, see _loc
DMAC = 0xFE008000                            # SH7724 DMAC0 register block
DMAC_LEN = 0x100
# CHCR TS[3:0] (bits 21:20, 4:3) -> transfer unit, as in emu/sh7724.py
TS_UNIT = {0: 1, 1: 2, 2: 4, 3: 16, 4: 32, 7: 8, 0xB: 16, 0xC: 32}


class Bus:
    def __init__(self, flash):
        self.flash = flash
        self.ram = bytearray(RAM_SIZE)
        self.ram_count = 0
        self.ram_written = bytearray(RAM_SIZE)
        self.dmac = bytearray(DMAC_LEN)      # register shadow, little-endian
        self.dma_log = []
        self.dev_reads = {}
        self.dev_writes = {}
        self.tick = None

    def _loc(self, a):
        m = a & 0x1FFFFFFF
        if m < len(self.flash):
            return "flash", m
        if 0x08000000 <= m < 0x18000000:
            # 0x08-0x0B bank0, 0x0C-0x0F bank1, 0x10-0x17 mirror of both
            return "ram", m & 0x07FFFFFF
        if DMAC <= a < DMAC + DMAC_LEN:
            return "dmac", a - DMAC
        return "dev", a

    def r8(self, a):
        k, o = self._loc(a)
        if k == "flash":
            return self.flash[o]
        if k == "ram":
            return self.ram[o]
        if k == "dmac":
            return self.dmac[o]
        self.dev_reads[a & ~3] = self.dev_reads.get(a & ~3, 0) + 1
        return 0

    def r16(self, a):
        return self.r8(a) | (self.r8(a + 1) << 8)

    def r32(self, a):
        return self.r16(a) | (self.r16(a + 2) << 16)

    def r64(self, a):
        return self.r32(a) | (self.r32(a + 4) << 32)

    def _w(self, a, v):
        k, o = self._loc(a)
        if k == "ram":
            if not self.ram_written[o]:
                self.ram_written[o] = 1
                self.ram_count += 1
            self.ram[o] = v & 0xFF
        elif k == "dmac":
            self.dmac[o] = v & 0xFF
        elif k == "dev":
            self.dev_writes[a & ~3] = self.dev_writes.get(a & ~3, 0) + 1

    def _store(self, a, v, size):
        for i in range(size):
            self._w(a + i, v >> (8 * i))
        if DMAC <= a < DMAC + DMAC_LEN:          # whole store done: check CHCR
            self._dma_check(a - DMAC)

    # -- DMAC0: channels 0-3 @ +0x20, DMAOR @ +0x60, channels 4-5 @ +0x70 ------
    def _dma_check(self, off):
        if 0x20 <= off < 0x60:
            base = 0x20 + (off - 0x20) // 16 * 16
        elif 0x70 <= off < 0x90:
            base = 0x70 + (off - 0x70) // 16 * 16
        else:
            return
        if off - base < 0xC:
            return
        sar, dar, tcr, chcr = struct.unpack_from("<4I", self.dmac, base)
        dmaor = struct.unpack_from("<H", self.dmac, 0x60)[0]
        if not (chcr & 1) or (chcr & 2) or not (dmaor & 1):
            return
        ts = (((chcr >> 20) & 3) << 2) | ((chcr >> 3) & 3)
        unit = TS_UNIT[ts]
        sm, dm = (chcr >> 12) & 3, (chcr >> 14) & 3
        n = (tcr & 0xFFFFFF) * unit
        step = {0: 0, 1: 1, 2: -1, 3: 0}
        ks, os_ = self._loc(sar)
        kd, od = self._loc(dar)
        if sm == 1 and dm == 1 and ks in ("flash", "ram") and kd == "ram":
            src = self.flash if ks == "flash" else self.ram
            self.ram[od:od + n] = src[os_:os_ + n]
            new = n - sum(self.ram_written[od:od + n])
            self.ram_written[od:od + n] = b"\x01" * n
            self.ram_count += new
        else:                                    # fixed/decrement: byte loop
            for i in range(n):
                s = sar + step[sm] * (i - i % unit) + i % unit if sm != 1 else sar + i
                d = dar + step[dm] * (i - i % unit) + i % unit if dm != 1 else dar + i
                self._w(d, self.r8(s))
        struct.pack_into("<I", self.dmac, base + 8, 0)
        struct.pack_into("<I", self.dmac, base + 12, chcr | 2)    # TE
        self.dma_log.append((sar, dar, n, chcr))

    def w8(self, a, v):
        self._store(a, v, 1)

    def w16(self, a, v):
        self._store(a, v, 2)

    def w32(self, a, v):
        self._store(a, v, 4)

    def w64(self, a, v):
        self.w32(a, v); self.w32(a + 4, v >> 32)

    def take_interrupt(self, imask):
        return None


def load_flash(upd):
    raw = open(upd, "rb").read()
    e1 = raw.index(b"\r\n") + 2
    e2 = raw.index(b"\r\n", e1) + 2
    sec = raw[e2:e2 + int(raw[:e1 - 2])]          # MAIN only
    flash = bytearray(b"\xff" * FLASH_SIZE)
    for line in sec.split(b"\r\n"):
        i = line.find(b"S2")
        if i < 0 or not line[i:].isalnum():
            continue
        rec = bytes.fromhex(line[i + 2:].decode("ascii"))
        ln = rec[0]
        addr = int.from_bytes(rec[1:4], "big")
        flash[addr:addr + ln - 4] = rec[4:ln]
    return bytes(flash), hashlib.sha256(raw).hexdigest()


def main():
    upd = sys.argv[1] if len(sys.argv) > 1 else UPD
    img_path = sys.argv[2] if len(sys.argv) > 2 else IMG
    DUMP = os.path.splitext(img_path)[0] + ".loader.img"     # beside the image it checks
    dump_key = os.path.relpath(os.path.abspath(DUMP), ROOT)
    img_key = os.path.relpath(os.path.abspath(img_path), ROOT)
    upd_key = os.path.relpath(os.path.abspath(upd), os.path.join(ROOT, "..", ".."))
    t0 = time.time()
    flash, in_sha = load_flash(upd)
    bus = Bus(flash)
    c = SH4(bus)
    c.reset()
    print(f"reset pc={c.pc:#x}")
    fixed = {"odd": 0, "delay": 0}
    in_ram = {"n": 0, "first": None}

    def tr(pc, op):
        if pc & 1:                                # hw quirk: odd jump target
            c.pc &= ~1
            fixed["odd"] += 1
            return
        # dt Rn (0100nnnn00010000) followed by bf back to it (0x8BFD)
        if (op & 0xF0FF) == 0x4010 and bus.r16(pc + 2) == 0x8BFD:
            n = (op >> 8) & 0xF
            if c.gr(n) > 0x10000:
                c.set_gr(n, 1)
                fixed["delay"] += 1
        # Done when the PC enters bank0 proper, where MAIN is unpacked. The
        # MK1 decompressor itself runs from RAM too (copied to the bank1
        # mirror at 0x17FFD000), so "PC in RAM" alone is not the end.
        m = pc & 0x1FFFFFFF
        if 0x08000000 <= m < 0x0C000000:
            in_ram["first"] = pc
            raise PcHalt(pc)

    c.trace = tr
    total, step = 0, 5_000_000
    for _ in range(200):
        res = c.run(limit=step)                  # "pc halt at ..." or "limit ..."
        total += step
        print(f"steps={total} pc={c.pc:#x} ram_written={bus.ram_count} "
              f"({bus.ram_count / 2**20:.1f} MB) t={time.time() - t0:.0f}s",
              flush=True)
        if res and res.startswith("pc halt"):
            print(f"jumped into MAIN at {in_ram['first']:#x} ({res})")
            break
    c.trace = None
    print("workarounds applied:", fixed)
    print(f"DMA transfers: {len(bus.dma_log)}", [(f"{s:#x}", f"{d:#x}", n, f"{c:#x}") for s, d, n, c in bus.dma_log[:8]])

    ref = open(img_path, "rb").read()
    n = len(ref)
    out = bytes(bus.ram[:n])                  # bank0 from 0x08000000
    out_sha = hashlib.sha256(out).hexdigest()
    ref_sha = hashlib.sha256(ref).hexdigest()
    os.makedirs(os.path.dirname(DUMP), exist_ok=True)
    open(DUMP, "wb").write(out)
    unwritten = n - sum(bus.ram_written[:n])
    past = sum(bus.ram_written[n:n + 0x10000])
    print(f"loader RAM : {n} bytes sha256 {out_sha}  (unwritten {unwritten}, "
          f"written in the 64 KB past the end {past})")
    print(f"unpacker   : {n} bytes sha256 {ref_sha}")
    match = out == ref
    if not match:
        d = next(i for i in range(n) if out[i] != ref[i])
        print(f"first difference at {d:#x}")
        print("top device reads:", sorted(bus.dev_reads.items(), key=lambda kv: -kv[1])[:8])
    print("RESULT:", "BYTE-FOR-BYTE MATCH" if match else "MISMATCH")

    man = json.load(open(MANIFEST)) if os.path.exists(MANIFEST) else {}
    man.setdefault("files", {})[dump_key] = {
        "role": "check", "made_by": "mk1/run_loader_mk1.py",
        "from": upd_key, "input_sha256": in_sha,
        "sha256": out_sha, "size": n, "unwritten": unwritten, "written_past_end_64k": past,
        "matches": img_key if match else None,
        "steps": total, "jump_to_ram": f"{in_ram['first']:#x}" if in_ram["first"] else None,
        "workarounds": fixed, "dma_transfers": len(bus.dma_log)}
    json.dump(man, open(MANIFEST, "w"), indent=2, sort_keys=True)
    open(MANIFEST, "a").write("\n")
    return 0 if match else 1


if __name__ == "__main__":
    sys.exit(main())
