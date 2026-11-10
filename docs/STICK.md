# The mods stick

Get `MODS.BIN` and `MODS2.BIN` from the project web page (drop your `XDJ1000.UPD`), or build them:

```bash
./xdjmod stick --upd XDJ1000.UPD [--waveform rgb|3band|blue] [--stems-screenshot PERFORM.png]
./xdjmod write --to /Volumes/MYSTICK
```

Copy both files (or let `write` copy them) to the **root** of any rekordbox USB stick (one that
has a `PIONEER` folder). Your music and the export stay untouched.

| File | Size | Role |
|---|---|---|
| `MODS.BIN` | 1.7 KB | read by the flashed loader: installs a second loader |
| `MODS2.BIN` | 240 KB (350 KB with stems) | read by the second loader in the same insert: all the mods |
| `MODSCFG.BIN` | 20 B | **written by the deck**: your WAVEFORM COLOR and PHASE METER settings |

Don't rename them. `MODS.BIN` and `MODS2.BIN` must both be there.

## Using it

1. Power-cycle the deck. The mods install once per power-on, and only while **no track is loaded**.
2. Insert the stick. The mods install while the deck reads the stick (a second or two).
3. Load a track: colour waveforms, phase meter, and so on.

Mods stay until power-off, even if you pull the stick. Another stick (with or
without the files) works normally. Its own `MODSCFG.BIN` settings, if it has
one, are applied when you insert it.

## Settings file (MODSCFG.BIN)

- **Read** on every stick insert, then applied.
- **Written** by the deck on the next track load from its own stick, but only after you
  changed WAVEFORM COLOR or PHASE METER in UTILITY. If nothing changed, it's
  never written. After 3 failed writes it stops trying until the next power-on.
- **Missing or damaged** means the defaults (the `--waveform` you built with, phase meter ON).
  Delete the file to reset.
- A change made right before power-off, with no track loaded afterwards, isn't saved.
- Pulling the stick during that brief write can damage this one file. The deck then ignores it.

## Troubleshooting

| Symptom | Check |
|---|---|
| Nothing changes after inserting the stick | UTILITY shows `1.13-MOD`? Both files in the stick **root**? Deck power-cycled, no track loaded before inserting? |
| Still nothing | `./xdjmod deck-status` over USB-B: the `loader status` line says why (`NOFILE`, `BADCRC`, `NOTSTOCK` = a track was loaded / mods already in, ...) |
| 3-BAND looks like RGB | that track has no `ANLZ0000.2EX` 3-band data: re-analyse it in rekordbox 6/7 and export again |
| Phase meter blue row has no ticks | the track has no beat grid; `deck-status` prints `pm_n` (beats found) and the deck's grid table |
| Blue waveform on a track loaded over LINK | expected: colour only comes from this deck's own stick ([MODS.md](MODS.md#colour-waveforms)) |
| Orange row mirrors your own deck | this deck is tempo master, which is how it should behave |

If you open an issue, include the `deck-status` output.
