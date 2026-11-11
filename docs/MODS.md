# The mods

All of them come from `MODS2.BIN` and live in RAM until power-off.

## Colour waveforms
The overview, centre and PERFORM waveforms in colour. UTILITY > **WAVEFORM COLOR**:
- **BLUE** = stock
- **RGB** = rekordbox's colour waveform
- **3-BAND** = rekordbox's 3-band waveform

The setting is saved on the stick ([STICK.md](STICK.md#settings-file-modscfgbin)).

**Tracks loaded over LINK get colour too (0.2.0).** The MK1 never receives colour
data from another player, so the mod fetches it: the other player's stick is
reachable as a drive, and at track load the mod finds the track in that stick's
`export.pdb` and reads the colour (PWV4/PWV5) and 3-band (PWV6/PWV7) sections from its
analysis files. This costs a little extra load time per LINK track. The data is only
shown when its length matches the loaded track; otherwise the waveform stays stock
blue. Tested with another XDJ-1000 MK1 and a CDJ-2000NXS as the source.
Built from XDJ Mod Studio's XDJ-700 code, with only the MK1 addresses
swapped in.

## 3-BAND from `.2EX`
rekordbox 6/7 writes the 3-band waveform (sections PWV6 and PWV7) into
`ANLZ0000.2EX`, a file the MK1 never reads. While a track loads, this mod
reads that file and hands the 3-band data to the waveform code, so a normal
export works and no special tool is needed. Tracks without 3-band data show
RGB in 3-BAND mode. The largest `.2EX` seen so far (933-track library) needs
421 KB, under the 512 KB buffer.

## Phase meter
Replaces the stock 4-box meter:
- **blue row** = this deck's beats. It uses the deck's own copy of the beat
  grid, so it works for tracks loaded from your own stick and over LINK.
- **orange row** = the tempo master. It follows whichever player the deck
  sees as master (players 1-6), using that player's beat packets. When this
  deck is master, the row mirrors its own beats.

UTILITY > **PHASE METER** ON/OFF (saved on the stick).
Tested: 2 real decks, plus qemu with 3 software players and a master
hand-over 3 → 4 → 2. Not tested: a DJM or rekordbox in the network.

## BEAT JUMP paging
On PERFORM, swipe the BEAT JUMP pad row sideways to change the jump sizes.
Limits:
- the '3' digit is drawn by us, not the stock font;
- the pads don't light up;
- the jump happens when you release the pad.

## Stems
Mute and solo vocals, drums, bass and other, live and sample-accurate, on
**STEMS-4 files**: a normal 16-bit WAV/AIFF mix plus 4 stem planes in one file.
You make them on the Mac from stems you separated yourself (for example with
Demucs). This needs `ffmpeg` (`brew install ffmpeg`):

```bash
.venv/bin/python src/tools/stems4.py build MIX.wav OUT.wav --vocals V.wav --drums D.wav --bass B.wav --other O.wav
```

On the deck, tap the **BEAT JUMP label** on PERFORM: the row becomes the STEMS
pads. Tap the label again to go back.

The STEMS pad graphics are cut from the deck's own PERFORM screen, so that
picture can't be in this repo. Build with
`--stems-screenshot PERFORM.png`. That's an 800×480 screenshot of the stock
PERFORM screen with a track loaded, taken in the emulator (the deck has no
screenshot function): see [TESTING.md](TESTING.md#stems-screenshot).
Without it, the stick has every other mod.

Other stem formats (for example OverCue's) aren't supported.

## Not included
**Key shift.** The XDJ-700 code exists, and it passes in qemu here. But it
writes into the running audio DSP, it can't be installed from a stick
safely, and upstream has an open report of a freeze plus a corrupted file.
