#!/usr/bin/env python3
"""Build a modded XDJ-1000 MK1 .UPD in work/ the way upstream's current builder
does it (tools/permanent_build.py), never flashed (CLAUDE.md rule 1).

Path (all upstream modules, unchanged):
  fwtool.parse -> decode block 1 with tools/lzss_boot.py from header+4 (the
  codec the emulated MK1 loader proved byte for byte) -> patch the decoded
  image -> lzss_boot.encode, round-trip checked -> fwtool write_block (length
  and block checksum) -> assemble -> re-parse the written file and check:
  every block checksum, block 1 decodes exactly to the intended image, boot
  stub + block 0 + PANL byte-identical to stock.

NOT used: build.sh -> setup_work.sh / updtool / repack / preflight. Those
decode from header+8 with tools/lzss, which treats the leading 01 00 EE FF as
a magic number; it is stream data (fwtool.py says so), and that decoder does
not reproduce the deck's image on the XDJ-700 or on MK1 (checked 2026-11-01).

Mods (addresses from mk1/models/xdj1000_113.json):
  flash         RGB / 3-band waveform + UTILITY rows baked in (permanent_mk1.py)
  version_tag   '-MOD' after the version in its own 32-byte field of the
                version record: UTILITY shows 'Ver 1.13-MOD'. (Upstream's
                mods/version_tag.py writes into block 0, the updater's own
                version table, which a normal boot never displays.)

  loader        stick loader baked in (loader_mk1.bake): boot copier puts the
                loader at its RAM home, mount-check pool word -> loader; the mods
                themselves stay on the stick (MODS.BIN, RAM only)
  --banner X.YY MAIN banner version the updater compares (official 1.13 is
                skipped by a 1.13 deck: deck test 2026-11-05)
    usage: python3 mk1/build_mk1.py [version_tag] [flash] [loader] [--banner 1.15]   -> work/mk1build/
"""
import hashlib
import re
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "tools"), HERE]
import fwtool                                                # noqa: E402
import lzss_boot as L                                        # noqa: E402

STOCK = os.environ.get("XDJMOD_UPD") or os.path.abspath(os.path.join(ROOT, "..", "..", "FW", "XDJ1000", "XDJ1000.UPD"))
OUT_DIR = os.path.join(ROOT, "work", "mk1build")
MODEL = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))
BASE = 0x08000000


def sha(b):
    return hashlib.sha256(b).hexdigest()


def version_tag(dec, tag=b"-MOD"):
    e = MODEL["entries"]["version_record"]
    at = int(e["fields"]["version"], 16) - BASE
    n = e["field_len"]
    want = e["expect"]["version"].encode()
    field = bytes(dec[at:at + n])
    if not field.startswith(want + b"\x00"):
        sys.exit(f"version field {field!r} is not {want!r}; refusing")
    new = want + tag + b"\x00"
    if field[len(want):len(new)] != b"\x00" + b" " * (len(new) - len(want) - 1):
        sys.exit("no NUL+space padding after the version; refusing to shift bytes")
    dec[at:at + len(new)] = new
    print(f"  version field {BASE + at:#010x}: {field[:12]!r} -> {bytes(dec[at:at + 12])!r}")


def flash(dec):
    """RGB / 3-band waveform + UTILITY rows baked in, boot copier (mk1/permanent_mk1.py)"""
    import permanent_mk1
    permanent_mk1.apply(dec)


def loader(dec):
    """stick loader baked in (mk1/loader_mk1.py)"""
    import loader_mk1
    loader_mk1.bake(dec)


def loaderx(dec):
    """loader X baked in: MODSX.BIN from the deck's own stick or the linked player's (mk1/mods_all.py)"""
    import mods_all
    mods_all.bake_x(dec)


def build(mods, banner=None):
    stock_raw = open(STOCK, "rb").read()
    if sha(stock_raw) != MODEL["upd_sha256"]:
        sys.exit("REFUSED: not the official XDJ-1000 v1.13 update file")
    raw, secs = fwtool.parse(STOCK)
    main = secs[0]
    hdr, ln = max(main.blocks(), key=lambda t: t[1])
    dec = bytearray(L.decode(bytes(main.img[hdr + 4:hdr + 4 + ln])))
    if sha(bytes(dec)) != MODEL["image_sha256"]:
        sys.exit("REFUSED: block 1 does not decode to the verified MK1 image")
    stock_dec = bytes(dec)
    for m in mods:
        print("==> mod:", m)
        {"version_tag": version_tag, "flash": flash, "loader": loader, "loaderx": loaderx}[m](dec)
    changed = [i for i in range(len(dec)) if i >= len(stock_dec) or dec[i] != stock_dec[i]]
    print(f"{len(changed)} bytes of the decoded image changed: "
          + ", ".join(f"{BASE + i:#010x}" for i in changed[:12]))
    print("compressing (about 30 s) ...")
    st = L.encode(bytes(dec))
    if L.decode(st) != bytes(dec):
        sys.exit("REFUSED: encoder round-trip failed")
    room = len(main.img) - (hdr + 4 + 2)
    print(f"flash slot: {room - len(st):,} B left")
    if len(st) > room:
        sys.exit(f"REFUSED: does not fit the flash slot ({len(st) - room:,} B over)")
    main.write_block(hdr, ln, st)
    print(f"block 1: {ln:,} -> {len(st):,} bytes ({len(st) - ln:+,})")
    if banner:
        mm = re.search(r"MAINVer(\d\.\d\d)", main.pre)
        if not mm or not re.fullmatch(r"\d\.\d\d", banner) or float(banner) <= float(mm.group(1)):
            sys.exit("REFUSED: banner %r must be d.dd and above %s" % (banner, mm and mm.group(1)))
        main.pre = main.pre[:mm.start(1)] + banner + main.pre[mm.end(1):]
        print(f"  MAIN banner Ver{mm.group(1)} -> Ver{banner} (section CRC recomputed on assemble)")
    os.makedirs(OUT_DIR, exist_ok=True)
    name = "XDJ1000_" + ("_".join(mods) if mods else "stock") + ("_v" + banner if banner else "") + ".UPD"
    out = os.path.join(OUT_DIR, name)
    open(out, "wb").write(fwtool.assemble(secs))
    # verify the written file
    _, chk = fwtool.parse(out)
    blocks = chk[0].check_blocks()
    if not all(okb for *_, okb in blocks):
        sys.exit("REFUSED: block checksum mismatch in the written file")
    h2, l2 = max(chk[0].blocks(), key=lambda t: t[1])
    if banner and ("MAINVer" + banner) not in chk[0].pre:
        sys.exit("REFUSED: banner not in the written file")
    if L.decode(bytes(chk[0].img[h2 + 4:h2 + 4 + l2])) != bytes(dec):
        sys.exit("REFUSED: written file does not decode to the intended image")
    _, s_secs = fwtool.parse(STOCK)
    sh, sl = min(s_secs[0].blocks(), key=lambda t: t[0])
    if bytes(chk[0].img[:sh + 4 + sl + 2]) != bytes(s_secs[0].img[:sh + 4 + sl + 2]):
        sys.exit("REFUSED: boot stub / block 0 changed")
    if chk[1].emit() != s_secs[1].emit():
        sys.exit("REFUSED: PANL section changed")
    img_out = os.path.join(OUT_DIR, "MAIN_mk1_113_" + ("_".join(mods) or "stock") + ".img")
    open(img_out, "wb").write(bytes(dec))
    print(f"written {out}\n  block checksums OK ({len(blocks)}), decodes exactly, boot stub + "
          f"block 0 + PANL identical to stock\n  UPD sha256 {sha(open(out, 'rb').read())}\n"
          f"  image {img_out} sha256 {sha(bytes(dec))}")
    return out, img_out


if __name__ == "__main__":
    av = sys.argv[1:]
    bn = None
    if "--banner" in av:
        i = av.index("--banner")
        bn = av[i + 1]
        del av[i:i + 2]
    build(av, bn)
