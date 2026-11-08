# MK1 platform reference

## Firmware files (`CDJ-Mods/FW/`, read-only)
| file | what | sha256 |
|---|---|---|
| `XDJ1000/XDJ1000.UPD` | MK1 v1.13, the target | `2da48a1b…94d75` |
| `XDJ1000 MK2/XDJ1KMK2.UPD` | MK2 v1.45, reference | `6fd2a500…02dbcd` |
| `XDJ1000 MK2/XDJ1KMK2_modded.UPD` | djpatcher output, reference only (closed source) | |
| `XDJ700/XDJ700.UPD` | XDJ-700 v1.15, the mods' source model (the hash `emu/fwhome.py` checks) | `73edec98…f99c` |
| `NXS/C2KNXS.UPD` | CDJ-2000NXS, not used | |

Unpacked images (git-ignored, `work/`): `MAIN_mk1_113.img` (`9863ea4d…`), `MAIN_mk2_145.img` (`46aaaed9…`), `MAIN_700_115.img` (`1875381b…`). All at base 0x08000000.

## Container and boot
- MK1 and MK2 UPDs share one format: decimal manifest, S2 records for MAIN, then PANL. Their first three boot records (flash 0x00–0x5F) are identical.
- MK1 is an SH7724 (SH-4 little-endian): its boot code drives DMAC0 (0xFE008000) and GPIO PADR (0xA4050100).
- MAIN is LZSS-packed (Pioneer's 4 KiB window): length at flash 0x40000, stream from 0x40004, 16-bit byte-sum after it. The loader copies the stream and its decompressor into RAM by DMA, unpacks to 0x08000000 and enters at 0xA8000800. Decoder: `tools/lzss_boot.py`; check any unpacker with `mk1/run_loader_mk1.py` (byte-for-byte against the emulated loader).
- Flash block 0 (0x10000) is the updater, with its own version table (MK1 `0.01`, 20140805).

## Memory map
- RAM: two 64 MB banks at 0x08000000 and 0x0C000000. 0x10000000–0x17FFFFFF is separate RAM on the deck (startup copies .data to 0x14109fc0), NOT a mirror as cdj-nxs2/`emu/machine.py` model it. Boot RAM test: P2 0xA8000000–0xB7FFFFFF.
  - On the deck 0x10000000–0x17FFFFFF is NOT a mirror (2026-11-01): startup's .data copy writes [0x08dddcc8, 0x08e223f8) to 0x14109fc0 (UTILITY table 0x14135ab4), and the deck reads 0 at the bank alias 0x0c135ab4. Startup order: CCR 0x808 -> DMA zero of bank 1 [0x0c000000, 0x0f309604) -> .data copy -> init-hook pool 0x080009e0 (stock fn 0x08c5d808 sets bit 1 of 0xa4050132) -> ... (models `startup`).
- The firmware keeps its heap, stacks and state in bank 1 (0x0C…–0x0F…). Bank 0 above the image (0x09200000–0x0C000000) is all zero in the emulator.
- Mod home in use: **0x09800000, 2 MB**. Deck survey 2026-11-01: untouched by the firmware, but power-on DRAM junk (95.6% 0xFF), NOT zero like qemu: every mod must zero what it relies on (test with `MK1_JUNK`).
- Zero runs inside the image are NOT usable as caves: r1 0x0885F820 is part of an 800×161 background image (the 2DG reads it); r2 0x08EC80E0 and r3 0x08E4AEF0 sit in a font/bitmap area.

## Deck USB shell (rear USB-B, VID 08E4 PID 01A6)
- HID: 64-byte output reports, no report IDs. Commands (table 0x0806dc34, names stored byte-reversed): `$CDJ` handshake ('Welcome' after boot, then 'E04'), `?V` version, `a,n-1BR` read (any address incl. P2 / 0x14 region), `a,vLW` one 32-bit store (handler 0x08acf200, reply 'R'), `a,vBW` byte store. Pace sessions ~30 s.
- Tools: `mk1/deck_read.py` (read-only), `mk1/deck_write.py` (gated writes), `mk1/deck_survey.py`, `mk1/link_scan.py`. RAM writes vanish at power-off.
- Other useful RAM: kernel ms clock 0x0dae5cdc; linked player status 0x0d2d04f0; models table has the rest.

## Version records
- Main app version record, 32-byte fields: vendor 0x08000700, model 0x08000720, version **0x08000740** (`1.13`), date 0x08000760. UTILITY › VERSION No. shows this one.
- Upstream `mods/version_tag.py` patches block 0's updater table, so its tag never shows in a normal boot. Our version tag patches the main app's field (`mk1/build_mk1.py`): `Ver 1.13-MOD`.

## Build pipeline
- Upstream `build.sh` (setup_work / updtool / repack / preflight) is the LEGACY path: it decodes from header+8 with `tools/lzss`, which does not reproduce the deck's image on the XDJ-700 or MK1.
- Build like `tools/permanent_build.py`: decode with `lzss_boot` from header+4, patch, re-encode with a round-trip check, `fwtool.write_block`, then verify the written file (checksums, exact decode, boot stub + block 0 + PANL identical to stock). For MK1: `mk1/build_mk1.py`.

## Model constants that differ (never inline them)
- Touch zone state: "no zone" 0x1E on the XDJ-700, **0x23 on MK1** (0x1E is MK1's hot-cue row; beat-jump pad 0x16).
- Full mapped tables with evidence: `mk1/models/xdj1000_113.json`, `mk1/traced_map.json`.
