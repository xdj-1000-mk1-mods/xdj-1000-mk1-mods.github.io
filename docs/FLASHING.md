# The stick loader enabler (flash once)

Drop your `XDJ1000.UPD` on the project's web page, which builds in your browser and uploads nothing. Or run
`./xdjmod firmware --upd XDJ1000.UPD`. Either way you get two files:

| File | What it is |
|---|---|
| `XDJ1000.UPD` (`XDJ1000_version_tag_loaderx_v1.17.UPD` from `xdjmod`) | the **enabler** (v2 since 0.2.0): stock 1.13 plus the stick loader |
| `XDJ1000_restore_1.16.UPD` | the **way back**: Pioneer's own 1.13, byte for byte, with only its version banner raised |

Both refuse any input file except the official XDJ-1000 v1.13 update (SHA-256
checked). Both compare their outputs with the hashes of the tested build: the
page offers nothing if they differ, and `xdjmod` warns. Do not flash a file that
`xdjmod` reports as "NOT the tested build".

## What the enabler changes

Compared with stock 1.13, the update file differs only in the decoded MAIN image:

- **The stick loader** (1.9 KB; 1.3 KB in the first enabler) goes into a free RAM area at power-on. A
  small boot copier, run from the firmware's init hook, puts it there.
- **A second pointer (enabler v2):** the Pro DJ Link code registers another player's
  stick as a drive through one firmware routine. Its pointer for that call also goes to
  the loader, which calls the stock routine first and then, if nothing is installed yet,
  looks for `MODSX.BIN` on that linked stick.
- **One pointer:** the firmware's USB-stick mount check builds the path of
  `PIONEER/rekordbox/export.pdb` through a pointer. That pointer now points
  to the loader, which calls the stock function first and returns the same
  result. Once per power-on it then looks for `MODSX.BIN` in the stick root
  (`MODS.BIN` on the first enabler). No file means nothing happens.
- **The version text** `1.13` becomes `1.13-MOD` (UTILITY > VERSION), so
  you can see that the enabler is installed.
- **The update file's banner** says `Ver1.17` (`Ver1.15` for the first enabler), so the
  updater accepts it as newer than 1.13 and shows that number on its screen.

The boot stub, the updater block and the panel firmware (PANL) are identical
to stock, and the build checks this. Every block checksum is recomputed,
and the written file is decoded again and compared with the intended image.

`MODS.BIN` is checked before anything is written. If anything is off (header,
CRC, an address outside the free RAM area, a hook that isn't stock, a track
already loaded), the loader writes nothing. Details:
[HOW_IT_WORKS.md](HOW_IT_WORKS.md).

## Installing it

**The file on the stick must be named exactly `XDJ1000.UPD`.** The deck's updater
looks for that name; with any other name it can't find the file and shows
"Connect USB storage device into top USB port." The web page already saves the
enabler under that name. `xdjmod` output and the restore file must be renamed.
You don't need `xdjmod` if you used the web page.

Install it exactly like an official firmware update. Put `XDJ1000.UPD` in
the root of a FAT32 USB stick with nothing else on it, use the deck's top USB port, then follow Pioneer
DJ's firmware update instructions for the XDJ-1000. Don't switch the deck
off while it updates.

Afterwards, UTILITY shows **1.13-MOD**. The deck behaves stock until you insert a
stick with `MODS.BIN` ([STICK.md](STICK.md)).

## Going back to stock

Rename `XDJ1000_restore_1.16.UPD` to `XDJ1000.UPD` and install it the same way. This is Pioneer's 1.13 with
only the version banner raised (3 bytes plus the checksum differ), because the
updater skips files that aren't newer. Afterwards the deck runs plain stock
1.13 and reports 1.13.

Tested on hardware so far:
- stock 1.13 → restore (built with banner 1.14) → stock 1.13 ✔
- stock 1.13 → first enabler (banner 1.15) → 1.13-MOD ✔
- first enabler → enabler v2 (banner 1.17) ✔

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
