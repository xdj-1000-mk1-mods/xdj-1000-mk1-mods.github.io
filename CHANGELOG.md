# Changelog

All versions are for the XDJ-1000 MK1 on firmware 1.13. The first enabler
(0.1.x) keeps working with every later version's `MODS.BIN` + `MODS2.BIN`; 0.2.0
adds a second enabler that can also load the mods over LINK.

## 0.2.0 (2026-11-11)

**New: colour and 3-band waveforms for tracks loaded over LINK.** When a deck loads a
track from another player's stick, the mod now looks the track up in that stick's
rekordbox database, reads the colour and 3-band data from its analysis files over the
link, and shows them. Before, LINK tracks were stock blue.

**New enabler (v2): mods load over LINK.** A deck with the new enabler gets the mods
from **its own stick or from the linked player's stick**, whichever shows up first. One
mods stick in one deck is enough for every linked MK1 that has the new enabler.

- Tested on real hardware: an XDJ-1000 MK1 with the new enabler, mods and colour over
  LINK from another deck's stick, and with a CDJ-2000NXS as the source player.
- Tested in qemu with two linked decks: mods over LINK; a damaged file (refused); the
  other deck joining later; a track already loaded (refused until the next power-on
  with no track loaded); colour data byte-identical to the source stick's files.
- **Stick files:** the page now gives three: `MODSX.BIN` (for the new enabler) and
  `MODS.BIN` + `MODS2.BIN` (for the first enabler). Put all three on the stick: each
  deck takes the ones it understands.
- **Do I need to reflash?** Only for "mods from the other deck's stick". Colour over
  LINK also works with the first enabler: just replace the stick files. To move to the
  new enabler, build it on the page and install it like before (`XDJ1000.UPD`); the
  restore file is unchanged.
- Known limits: each LINK load reads the other stick's database and analysis files
  first, which adds a little load time (more on big libraries; not measured yet). Builds
  with stems have no tested reference in this version.

Enabler v2 sha256 `f61d2f5c…`, `MODSX.BIN` `fd14c59c…`, `MODS2.BIN` `8a4d163f…`,
`MODS.BIN` `52e09b74…` (unchanged), restore `7c8419b4…` (unchanged).

## 0.1.3 (2026-11-10)

**Fixed: colour waveform stuck on an earlier song for tracks loaded over LINK.**
A track loaded over Pro DJ Link from another player's USB never fills the place
the colour waveform is read from, so the overview and the big waveform kept
showing the colours of the last track loaded from the deck's own stick. The same
thing happened after moving the mods stick to the other deck. Now the deck checks
that the colour data belongs to the loaded track (by comparing beat grids), and
shows the stock blue waveform when it doesn't.

- LINK tracks show the stock blue waveform; the MK1 doesn't receive colour data for
  them. For colour on both decks, keep the mods stick in the MK1 and let the other
  player load from it over LINK. Fetching colour over LINK is being looked into.
- Update: rebuild on the page and replace **`MODS2.BIN`** on your stick. `MODS.BIN`
  and the enabler are unchanged.
- Tested in qemu with two linked decks: the old build shows the previous track's
  colours, the new one doesn't (`src/mk1/link_rgb_emu.py`).

`MODS2.BIN` sha256 `2e17d033…` (page / no stems), `efe58fc7…` (with stems).

## 0.1.2 (2026-11-09)

**Fixed: the update didn't start ("Connect USB storage device into top USB port").**
The deck's updater only looks for a file named exactly `XDJ1000.UPD`. The page now
saves the enabler under that name, and the docs explain the rename for the restore
file and for `xdjmod` output. The file contents didn't change: renaming an earlier
download works too.

## 0.1.1 (2026-11-08)

First public version.

- Web page: drop the official `XDJ1000.UPD` (v1.13) and get the stick-loader enabler,
  the stock restore, `MODS.BIN` and `MODS2.BIN`, built in your browser.
- Mods: colour and 3-band waveforms (3-band from rekordbox's `.2EX`), phase meter with
  the tempo master's row (any player, also for LINK loads), WAVEFORM COLOR and PHASE
  METER saved per stick, BEAT JUMP paging; stems mixer via the command line.
- Enabler sha256 `9bc1f58e…`, restore `7c8419b4…`.
