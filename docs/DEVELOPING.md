# Developing

## Layout
```
xdjmod                      the command-line tool (wraps the scripts below)
src/mk1/                    the MK1 port: one builder per mod (*_mk1.py) + its C/asm sources
  models/xdj1000_113.json   EVERY firmware address and constant, each with evidence
  loader/                   stick loader (ldr.c: loader1 in the enabler, loader2 from MODS.BIN)
  ext2/                     3-band from .2EX + the settings writer
  bjswipe/ stemsui/ utility/ ksui/   module sources
  build_mk1.py              enabler UPD (version tag + loader + boot copier)
  restore_mk1.py            stock restore UPD (banner raised)
  rgb_mk1.py, make_snapshot.py       colour waveforms, UTILITY rows, phase meter
  mods_all.py               MODS.BIN + MODS2.BIN (and the combined qemu test)
  deck_write.py             USB-B deck access: `loader-status`, `pm-status` read only;
                            the RAM-install commands write (only with --go)
  emu.py, *_emu.py          qemu tests (docs/TESTING.md)
  docs/PLATFORM.md, docs/EMULATOR.md  platform + emulator notes
src/tools/                  upstream XDJ Mod Studio sources this port compiles
                            (phase meter, stems, centre waveform, LZSS, UPD tools, compiler build)
src/work/                   everything generated (git-ignored): unpacked image, builds, compiler
```

The build scripts take these environment variables (`xdjmod` sets them for you):
| Variable | Meaning |
|---|---|
| `XDJMOD_UPD` | the update file |
| `XDJMOD_SNAP` | the module snapshot folder |
| `XDJMOD_STEMS=0/1` | build with or without stems |
| `XDJMOD_NXS2` | the emulator folder |

## The model table
`src/mk1/models/xdj1000_113.json` is the only place firmware addresses live.
Each entry carries its **evidence**: which instruction or literal pool, which
qemu run, which read-only deck reading. Anything not proven is marked
`"unverified": true`. When you find something new, add it there first and build
from it. Never hard-code an address in C or Python.

## Adding a mod
1. Find the hook point in qemu. `emu.py` gives you gdb, memory reads and
   screenshots, and `link_scan.py` / `match.py` map XDJ-700 addresses to MK1 ones.
2. Write a builder `src/mk1/<mod>_mk1.py`: `build()` returns the module image and
   its symbols, and `install_steps()` lists the order (blocks first, the hook
   STORE last).
3. Put it in `mods_all.plan2()`. Hooks shared by several mods are chained by
   presetting each module's `prev` pointer. `plan2` refuses broken chains and lists
   overlapping blocks.
4. Write a qemu test. Read-only deck checks come next, and only then a stick on
   real hardware.

Don't touch `loader/ldr.c` behaviour outside `#ifdef CFG_NAME` (loader2-only):
loader1 is flashed, and `mods_all.py` refuses to build if loader1 changes
(sha256 `0752ff81…`).

## Never commit
Firmware, decoded images (`*.img`), built updates (`*.UPD`), stick files (`*.BIN`),
qemu states (`*.vm`), RAM dumps, or screenshots of the deck's screens. The
`.gitignore` covers these; check `git status` before every commit anyway.
