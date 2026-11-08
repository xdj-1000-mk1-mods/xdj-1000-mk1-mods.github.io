#!/usr/bin/env python3
"""Stock-restore UPD: official XDJ-1000 v1.13 with ONLY the MAIN banner version raised.

    .venv/bin/python mk1/restore_mk1.py [NEWVER]        (default 1.14; from xdj-mod-studio/)

Idea from LNNRT Mods (NXS1): the player skips an update that is not newer than
what it runs, so Pioneer's own file is re-labelled newer. The MAIN payload (every
S2 record), block 0, the boot stub and the PANL section stay byte-identical; only
the 4 version characters in the MAIN preamble and that section's CRC16 change.

Checks (all must pass or nothing is written):
  - input sha256 == the known official 1.13 file
  - fwtool parse + re-emit of the stock file is byte-identical (proves the CRC16
    algorithm and framing are right for MK1)
  - output: same length; differing bytes lie only in the banner digits + MAIN CRC;
    every S2 record and the PANL section identical; re-parse OK
"""
import hashlib, json, os, re, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # xdj-mod-studio
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import fwtool

STOCK = os.environ.get('XDJMOD_UPD') or os.path.normpath(os.path.join(ROOT, '..', '..', 'FW', 'XDJ1000', 'XDJ1000.UPD'))
STOCK_SHA = '2da48a1baa999e3c36f62b7b7f1732a6f4c7ca2a37f636c13b0b3cbf8de94d75'
OUTDIR = os.path.join(ROOT, 'work', 'mk1restore')


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    new = sys.argv[1] if len(sys.argv) > 1 else '1.14'
    if not re.fullmatch(r'\d\.\d\d', new):
        sys.exit('version must look like 1.14')
    raw = open(STOCK, 'rb').read()
    if sha(raw) != STOCK_SHA:
        sys.exit('input is not the official v1.13 file')
    _, secs = fwtool.parse(STOCK)
    if fwtool.assemble(secs) != raw:
        sys.exit('stock re-emit differs: framing/CRC not understood, refusing')
    main_i = [i for i, s in enumerate(secs) if 'MAINVer' in s.pre]
    if len(main_i) != 1:
        sys.exit('MAIN section not found exactly once')
    s = secs[main_i[0]]
    m = re.search(r'MAINVer(\d\.\d\d)', s.pre)
    old = m.group(1)
    if old != '1.13' or float(new) <= float(old):
        sys.exit(f'banner is {old}; new version {new} must be higher')
    s.pre = s.pre[:m.start(1)] + new + s.pre[m.end(1):]
    out = fwtool.assemble(secs)

    # --- verify ---
    assert len(out) == len(raw), 'length changed'
    diff = [i for i in range(len(raw)) if raw[i] != out[i]]
    hdr_len = raw.index(b'\r\n', raw.index(b'\r\n') + 2) + 2
    sec_off = hdr_len + sum(len(x.blob) for x in secs[:main_i[0]])
    ver_off = sec_off + m.start(1)
    crc_off = sec_off + len(s.blob) - 2
    allowed = set(range(ver_off, ver_off + 4)) | {crc_off, crc_off + 1}
    assert diff and set(diff) <= allowed, f'unexpected diffs at {[hex(i) for i in diff if i not in allowed][:8]}'
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, f'XDJ1000_restore_{new}.UPD')
    tmp = path + '.tmp'
    open(tmp, 'wb').write(out)
    _, secs2 = fwtool.parse(tmp)
    for a, b in zip(secs, secs2):
        assert a.recs == b.recs and a.img == b.img, 'S2 payload differs after re-parse'
        assert b.blob[-2:] == struct.pack('<H', fwtool.crc16_xmodem(b.blob[:-2])), 'CRC bad'
    os.replace(tmp, path)

    # --- manifest ---
    mp = os.path.join(HERE, 'manifest.json')
    man = json.load(open(mp)) if os.path.exists(mp) else {'files': {}}      # release tree: no dev manifest
    rel = os.path.relpath(path, ROOT)
    man['files'][rel] = {
        'role': 'output', 'from': 'FW/XDJ1000/XDJ1000.UPD', 'made_by': 'mk1/restore_mk1.py ' + new,
        'what': f'stock restore: MAIN banner Ver{old} -> Ver{new}, MAIN CRC16 recomputed; payload + PANL identical',
        'sha256': sha(out), 'size': len(out),
        'diff_offsets': [hex(i) for i in diff],
    }
    if os.path.exists(mp):
        json.dump(man, open(mp, 'w'), indent=2, sort_keys=True)
    print(f'banner Ver{old} -> Ver{new}; {len(diff)} bytes differ at {[hex(i) for i in diff]}')
    print(f'MAIN CRC {raw[crc_off:crc_off+2].hex()} -> {out[crc_off:crc_off+2].hex()}')
    print(f'{rel}  sha256 {sha(out)}')


if __name__ == '__main__':
    main()
