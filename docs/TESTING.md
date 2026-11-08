# Testing

Every mod is tested in qemu before it goes near a deck, and the first contact
with a deck is read-only. The emulator is
[cdj-nxs2-qemu](https://github.com/Stijn-Jacobs/cdj-nxs2-qemu) (GPL-2.0, not
included), set up for the XDJ-1000 with **your own** firmware.

## Setup
1. Install cdj-nxs2-qemu following its README, with model `xdj1000` and your
   `XDJ1000.UPD`.
2. Tell this repo where it is: `export XDJMOD_NXS2=/path/to/cdj-nxs2`.
   The default is the `cdj-nxs2` folder next to this repo's folder.
3. Build once (`./xdjmod firmware ...` and `./xdjmod stick ...`), so that `src/work/` has
   the unpacked image and the enabler image.
4. Test inputs, made from your own material (git-ignored, never commit them):
   - `src/work/testusb/device/`: a small rekordbox export (the `PIONEER` folder plus a
     few tracks, analysed by rekordbox 6/7, so 3-band `.2EX` data is present). The
     stick tests build their stick images from it.
   - `src/work/testusb/test_usb.img`: an image of that folder for `emu.py boot`, made
     with cdj-nxs2's `scripts/media/make_usb_image.py <folder> <img> 64`.
   - `src/work/emu/xdj1000/perform.vm`: a saved qemu state with a track loaded, on
     PERFORM. Boot, load a track, tap PERFORM, then
     `../.venv/bin/python mk1/emu.py save xdj1000 perform`. Used by the phase meter
     tests.
   - optional `src/work/survey/ram_09800000.bin` / `ram_09a00000.bin`: the free RAM
     of a real deck (`mk1/deck_survey.py`, read-only). Without them the free RAM
     starts zeroed.

Run the tests from `src/`, with the repo's Python (`../.venv/bin/python`).

| Test | What it checks |
|---|---|
| `mk1/mods_all.py emu` | Cold boot of the enabler image, with RAM pre-filled the way a real deck has it, and a stick with `MODS.BIN` + `MODS2.BIN`. Checks: both loaders run in one mount; every hook word changes; a track loads with 3-band data from `.2EX`; BEAT JUMP swipe; STEMS label; UTILITY. Set `XDJMOD_STEMS=0` to test the build without stems. |
| `mk1/mods_all.py emu --link` | The same, on an emulated Pro DJ Link network with 3 software players. The orange row must follow the master through a hand-over 3 → 4 → 2. |
| `mk1/phasemeter_mk1.py emu` | Phase meter on main and PERFORM, compared against the expected drawing; BROWSE; ON/OFF |
| `mk1/late_grid_emu.py` | The beat grid arrives after the track does (as on LINK loads) and is still picked up |
| `mk1/link_load_emu.py` | Two linked emulated decks: deck B loads from deck A's USB over LINK, and its meter finds the grid |
| `mk1/settings_emu.py` | Writable stick: `MODSCFG.BIN` is written once after a change. Checks the bytes from the Mac, `fsck_msdos` stays clean, and the settings return after a reboot |
| `mk1/loader_mk1.py emu ok\|refuse\|badcrc\|nofile` | loader1 against good, refused (track loaded), corrupt and missing files |
| `mk1/stems_mk1.py emu` | stems mixer output against reference mixes |

**macOS notes:**
- The emulated Pro DJ Link network runs over multicast on loopback (`mk1/net_lo.py`),
  because macOS blocks Wi-Fi multicast for these processes.
- Keep the Mac awake and on power during the tests (`caffeinate -dis ...`). When an idle
  Mac on battery starves qemu of CPU, the network tests fail in confusing ways (for
  example, the emulated deck takes the master role itself).

## Stems screenshot
The STEMS pads are cut from a picture of the stock PERFORM screen with a track
loaded, and the deck itself can't take screenshots. With the emulator:

```bash
cd src
../.venv/bin/python mk1/emu.py boot xdj1000 &        # stock deck, work/testusb/test_usb.img
# wait for the main screen, load a track (USB, select, load), then:
../.venv/bin/python mk1/emu.py tap  xdj1000 711 37    # PERFORM
../.venv/bin/python mk1/emu.py shot xdj1000 ~/perform.png
../.venv/bin/python mk1/emu.py cmd  xdj1000 quit
cd .. && ./xdjmod stick --upd XDJ1000.UPD --stems-screenshot ~/perform.png
```
The picture is derived from the firmware: keep it to yourself and never commit it.

## The web page
`web/core.js` is a byte-exact JavaScript port of the UPD/LZSS build.
- `node web/test.mjs XDJ1000.UPD` builds both files the way the page does, and checks
  them against the tested hashes (about 3 s).
- The page also builds `MODS.BIN` + `MODS2.BIN`. They come from `web/stick.json` (our bytes) plus the
  BEAT JUMP labels, rendered in the browser by `src/mk1/bjlabels.py` under Pyodide.
- After a change to the enabler or the stick, run `./xdjmod firmware ...` and `./xdjmod stick ...`
  (no stems, rgb), then `.venv/bin/python web/make_patch.py` to regenerate `web/patch.json` and
  `web/stick.json`.
- Local preview: `python3 -m http.server` in the repo root, then open http://localhost:8000/
  (tested in headless Chrome: all 4 files built in about 6 s, byte-identical).

## Hardware, read-only
`./xdjmod deck-status` (deck on USB-B) reads the loader state, the phase meter
counters, the deck's beat grid table and every player's slot. It never writes.
