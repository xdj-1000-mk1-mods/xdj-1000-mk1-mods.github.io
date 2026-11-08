#!/usr/bin/env python3
"""Unpack XDJ-1000 (MK1) MAIN: S-records -> flash image -> LZSS -> unpacked.

Based on tools/unpack_1000.py (MK2). Differences:
  - reads FW/XDJ1000/XDJ1000.UPD, no hard-coded input/output hash
  - splits MAIN from PANL by the UPD's own decimal manifest, not by
    "address went down"
  - checks every S-record checksum and the image's 16-bit sum (the one the
    deck's loader verifies before it unpacks)
  - records input/output SHA-256 in mk1/manifest.json

Packed layout at flash 0x40000 (same as MK2):
  [LE32 len][LZSS stream, len bytes][LE16 sum of bytes from len field to
  end of stream]
The truth check is mk1/run_loader_mk1.py: the deck's own loader, emulated.

    usage: python3 mk1/unpack_mk1.py [UPD] [OUT]     (from xdj-mod-studio/)
    MK2 (same layout): python3 mk1/unpack_mk1.py "../../FW/XDJ1000 MK2/XDJ1KMK2.UPD" work/MAIN_mk2_145.img
"""
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # xdj-mod-studio/
CDJ_MODS = os.path.abspath(os.path.join(ROOT, "..", ".."))
sys.path.insert(0, ROOT)
from tools.lzss_boot import decode as L

UPD = os.path.join(ROOT, "..", "..", "FW", "XDJ1000", "XDJ1000.UPD")
OUT = os.path.join(ROOT, "work", "MAIN_mk1_113.img")
MANIFEST = os.path.join(HERE, "manifest.json")
PACKED_OFF = 0x40000
BASE = 0x08000000                                 # where the loader unpacks to
FLASH_SIZE = 0xB00000


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main_section(raw):
    """(label, section bytes) of MAIN, the first section in the manifest."""
    e1 = raw.index(b"\r\n") + 2
    e2 = raw.index(b"\r\n", e1) + 2
    main_len = int(raw[:e1 - 2])
    sec = raw[e2:e2 + main_len]
    return sec[:32].split(b"\x00")[0].decode("latin1"), sec


def flash_from_section(sec):
    flash = bytearray(b"\xff" * FLASH_SIZE)
    n = 0
    for line in sec.split(b"\r\n"):
        i = line.find(b"S2")
        if i < 0 or not line[i:].isalnum():
            continue
        rec = bytes.fromhex(line[i + 2:].decode("ascii"))
        ln = rec[0]
        assert len(rec) == ln + 1, "bad S2 length"
        assert (sum(rec) & 0xFF) == 0xFF, "bad S2 checksum"
        addr = int.from_bytes(rec[1:4], "big")
        flash[addr:addr + ln - 4] = rec[4:ln]      # ln-4 data bytes
        n += 1
    return flash, n


def record(entries):
    man = {}
    if os.path.exists(MANIFEST):
        man = json.load(open(MANIFEST))
    man.setdefault("files", {}).update(entries)
    json.dump(man, open(MANIFEST, "w"), indent=2, sort_keys=True)
    open(MANIFEST, "a").write("\n")


def main():
    upd = sys.argv[1] if len(sys.argv) > 1 else UPD
    out_path = sys.argv[2] if len(sys.argv) > 2 else OUT
    raw = open(upd, "rb").read()
    in_sha = sha(raw)
    label, sec = main_section(raw)
    print("input :", os.path.relpath(upd), in_sha)
    print("label :", label)

    flash, n = flash_from_section(sec)
    print("MAIN S2 records:", n)
    (plen,) = struct.unpack_from("<I", flash, PACKED_OFF)
    stream = bytes(flash[PACKED_OFF + 4:PACKED_OFF + 4 + plen])
    (stored,) = struct.unpack_from("<H", flash, PACKED_OFF + 4 + plen)
    calc = sum(flash[PACKED_OFF:PACKED_OFF + 4 + plen]) & 0xFFFF
    print(f"packed: off={PACKED_OFF:#x} len={plen:#x} sum16 stored={stored:#06x} "
          f"calc={calc:#06x} {'OK' if stored == calc else 'MISMATCH'}")
    if stored != calc:
        return 1

    img = L(stream)
    out_sha = sha(img)
    print(f"output: {len(img)} bytes ({len(img):#x}) base {BASE:#010x} sha256 {out_sha}")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    open(out_path, "wb").write(img)
    print("wrote", os.path.relpath(out_path))

    in_key = os.path.relpath(os.path.abspath(upd), CDJ_MODS)      # FW/...
    out_key = os.path.relpath(os.path.abspath(out_path), ROOT)    # work/...
    record({
        in_key: {
            "role": "input", "label": label,
            "sha256": in_sha, "size": len(raw)},
        out_key: {
            "role": "output", "made_by": "mk1/unpack_mk1.py",
            "from": in_key, "sha256": out_sha,
            "size": len(img), "base": f"{BASE:#010x}",
            "packed_off": f"{PACKED_OFF:#x}", "packed_len": plen,
            "sum16": f"{stored:#06x}"},
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
