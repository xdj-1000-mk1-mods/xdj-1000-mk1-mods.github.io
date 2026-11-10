# Changelog

All versions are for the XDJ-1000 MK1 on firmware 1.13. The enabler
(`XDJ1000.UPD`) has not changed since 0.1.1, so no reflash is needed between
these versions.

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
