# How it works

The XDJ-1000 MK1 is an SH7724 (SH-4, little endian). MAIN is LZSS-packed in
the update file and unpacked to RAM at 0x08000000. More detail:
`src/mk1/docs/PLATFORM.md`.

## 1. The enabler (flashed)
A boot copier on the init hook copies the **stick loader** (loader1,
`src/mk1/loader/`) to 0x099f0000. The pointer at 0x08b77220, which the
USB-stick mount check calls to build file paths, is set to `ldr_path_build`.
That function:
1. calls the stock path builder (same result for the firmware);
2. on the `export.pdb` lookup, once per power-on: opens `<stick>:/MODS.BIN` with the
   firmware's own file calls, checks it (pass 1), then applies it (pass 2).

## 2. MODS.BIN / MODS2.BIN format
```
u32 'MODS', u32 1, u32 total bytes, u32 crc32(bytes 16..)
ops: CHECK addr val | COPY dst len flags data | ZERO dst len flags |
     MEMCPY dst src len flags | STORE addr stock new flags | END
```
- Pass 1 checks everything and writes nothing. That includes: every destination lies in
  free RAM (not over the loader); every `CHECK` holds; every `STORE`'s word still holds
  its stock value.
- Pass 2 writes, in file order. Code is written to cached and uncached memory, so it
  reaches RAM before the CPU fetches it.

**`MODS.BIN`** is tiny. It installs **loader2** (the same `ldr.c`, built with other
addresses, at 0x099ee000) and points the mount-check pointer from loader1 to loader2.
The firmware asks for `exportExt.pdb` during the same mount, which runs loader2. Loader2
reads **`MODS2.BIN`** (up to 512 KB) through a staging buffer at 0x09a00000, and then
applies the stick's `MODSCFG.BIN` on every mount. That buffer is free again afterwards:
the 3-band reader uses it.

## 3. Memory map (free RAM, surveyed on a real deck)
| Range | What |
|---|---|
| 0x09800000.. | colour-waveform caves and buffers |
| 0x09804000 | UTILITY rows module |
| 0x09806000 | BEAT JUMP paging |
| 0x09814000.. | waveform slot buffers |
| 0x09854000 | stems mixer |
| 0x098c0000 | phase meter |
| 0x098e0000 | STEMS UI |
| 0x099ec000 | `.2EX` 3-band reader + settings writer |
| 0x099ee000 | loader2 (state 0x099eff00, drive word 0x099effc0, settings state 0x099effd0) |
| 0x099f0000 | loader1 (flashed; state 0x099f0f00, stage to 0x09a00000) |
| 0x09a00000-0x09a80000 | loader2 stage, then the `.2EX` buffer |

## 4. Hooks (what each mod hangs on)
| Hook | Used by |
|---|---|
| display flush slot 0x08c37f14 | STEMS UI → phase meter → stock |
| touch slot 0x08cf94f4 | STEMS UI → BEAT JUMP paging → stock |
| `.EXT` parse pointer 0x08cae4ac | 3-band reader + settings writer |
| file read 0x08d06c98 / 0x08d86bb4 | stems mixer |
| waveform painters (several) | colour waveforms |

Every address, with its evidence, is in `src/mk1/models/xdj1000_113.json`.

## 5. Phase meter data
- **This deck:** the firmware's own copy of the loaded track's grid, at 0x0e43c10c
  (valid), 0x0e43c110 (count) and 0x0e43c114 (entries {ms, beat-in-bar}). It's filled
  for USB and LINK loads. The meter takes it again whenever the table changes, because
  on a LINK load the grid arrives over the network after the track does.
- **Master:** the firmware's tempo-master player number is at 0x0d2be2d4. Each
  player's status packet is at 0x0d2d011c + n×0x11c (flags +0x89, BPM +0x90, pitch
  +0x8c). The beat byte (packet-timed) is at 0x0d2be62c + n. The sub-beat position comes
  from the kernel's millisecond clock.

## 6. Settings file
`MODSCFG.BIN` is 20 bytes, little-endian:
`'MCFG', 1, wave (0-2), pm (0-1), magic^1^wave^pm^0x5A5A5A5A`.
- **Read** by loader2 on every mount.
- **Written** by the 3-band module right after the firmware parses a track's `.EXT`
  (a moment when the deck is reading that stick anyway). It uses `fopen(w)`, `fwrite`
  and `fclose`, the same calls as the firmware's own USB screen dump, and writes only
  when a value changed.
