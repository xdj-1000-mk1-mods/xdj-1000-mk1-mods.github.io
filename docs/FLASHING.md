# The stick loader enabler (flash once)

Drop your `XDJ1000.UPD` on the project's web page, which builds in your browser and uploads nothing. Or run
`./xdjmod firmware --upd XDJ1000.UPD`. Either way you get two files:

| File | What it is |
|---|---|
| `XDJ1000_version_tag_loader_v1.15.UPD` | the **enabler**: stock 1.13 plus the stick loader |
| `XDJ1000_restore_1.16.UPD` | the **way back**: Pioneer's own 1.13, byte for byte, with only its version banner raised |

Both refuse any input file except the official XDJ-1000 v1.13 update (SHA-256
checked). Both compare their outputs with the hashes of the tested build: the
page offers nothing if they differ, and `xdjmod` warns. Do not flash a file that
`xdjmod` reports as "NOT the tested build".

## What the enabler changes

Compared with stock 1.13, the update file differs only in the decoded MAIN image:

- **The stick loader** (1.3 KB) goes into a free RAM area at power-on. A
  small boot copier, run from the firmware's init hook, puts it there.
- **One pointer:** the firmware's USB-stick mount check builds the path of
  `PIONEER/rekordbox/export.pdb` through a pointer. That pointer now points
  to the loader, which calls the stock function first and returns the same
  result. Once per power-on it then looks for `MODS.BIN` in the stick root.
  No file means nothing happens.
- **The version text** `1.13` becomes `1.13-MOD` (UTILITY > VERSION), so
  you can see that the enabler is installed.
- **The update file's banner** says `Ver1.15`, so the updater accepts it as
  newer than 1.13. The updater screen therefore says "1.13 to 1.15".

The boot stub, the updater block and the panel firmware (PANL) are identical
to stock, and the build checks this. Every block checksum is recomputed,
and the written file is decoded again and compared with the intended image.

`MODS.BIN` is checked before anything is written. If anything is off (header,
CRC, an address outside the free RAM area, a hook that isn't stock, a track
already loaded), the loader writes nothing. Details:
[HOW_IT_WORKS.md](HOW_IT_WORKS.md).

## Installing it

Install it exactly like an official firmware update. Put the `.UPD` file in
the root of a FAT32 USB stick with nothing else on it, then follow Pioneer
DJ's firmware update instructions for the XDJ-1000. Don't switch the deck
off while it updates.

Afterwards, UTILITY shows **1.13-MOD**. The deck behaves stock until you insert a
stick with `MODS.BIN` ([STICK.md](STICK.md)).

## Going back to stock

Install `XDJ1000_restore_1.16.UPD` the same way. This is Pioneer's 1.13 with
only the version banner raised (3 bytes plus the checksum differ), because the
updater skips files that aren't newer. Afterwards the deck runs plain stock
1.13 and reports 1.13.

Tested on hardware so far:
- stock 1.13 → restore (built with banner 1.14) → stock 1.13 ✔
- stock 1.13 → enabler (banner 1.15) → 1.13-MOD ✔

The 1.16 restore over the enabler is the same kind of file, but nobody has
tried it on a deck yet. If you do, please report back.

**Future official updates:** the deck compares an update with the version it
runs (1.13), so an official update newer than 1.13 should install normally,
with or without the enabler.

## Checking an enabled deck (optional, read-only)

Connect the deck's rear USB-B port to the Mac, then run:

```bash
./xdjmod deck-status
```

This shows whether the loader ran on the last stick insert (`status OK, done`),
plus the phase meter state. It only reads.
