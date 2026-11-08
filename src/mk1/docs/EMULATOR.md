# Emulators and our tools

## cdj-nxs2 (qemu), `CDJ-Mods/cdj-nxs2/`
- Upstream commit `63a5186`, QEMU 11.1.2. Start the MK1: `./start.sh --model xdj1000`. `cdj.conf` says `CDJ_MODEL=xdj1000`; the CDJ-2000NXS config is in `cdj.conf.nxs` (copy it back to switch).
- Builds: `~/qemu-build` (MAIN, `qemu-system-sh4`). `~/qemu-build-eb` (display board) is NXS2-only and not built. DSP modules: `~/c14gen/curated-xdj1000/`, `~/c14gen/curated-xdj700/`. Old 9.1.0 source: `cdj-nxs2/qemu-src-9.1.0`.
- Venv: `cdj-nxs2/.venv` (pyfatfs, mutagen). Local fix kept on top of upstream: `scripts/media/make_usb_image.py` (pyfatfs refuses folder names with spaces; still needed at `63a5186`).
- Debug knobs: `CDJ_FWTRACE=pc,...` (pc pr r0 r4 r5 per pass), `CDJ_MWATCH=addr,...` (writer PC of up to 4 words), `CDJ_PPOKE=pc:addr:or:and[:n]` (word write before pc runs), `CDJ_PCALL2=anchor:func:r4:r5:r6` (call a firmware function once), `CDJ_2DG_LOG=1` (every 2DG op), `CDJ_TOUCH=1` + panel UDP `x:y:ms:tap`. Select knob: report byte `0x0E` (`key 0x0e:1:0:rot`).

## Update procedure
1. `cd cdj-nxs2 && git stash push -m "pyfatfs spaced-name fix" scripts/media/make_usb_image.py`
2. `git pull --ff-only && git stash pop` (merge by hand on conflict; drop the fix if upstream fixed spaced names)
3. `cp cdj.conf cdj.conf.bak`, then `./setup.sh --rebuild -y --model xdj1000 --firmware "../FW/XDJ1000/XDJ1000.UPD"`. `--rebuild` matters: without it setup keeps the old build even when QEMU's version moved.
4. Rerun our emulator checks. A QEMU update invalidates saved states (`work/emu/<model>/*.vm`) and may change the plugin API (`mk1/tools/tbcov.c`).

## Our tools (`CFW/xdj-mod-studio/mk1/`)
| tool | what |
|---|---|
| `emu.py` | headless deck via cdj-nxs2's launcher: monitor, gdbstub, saved states, scripted input (`tap`, `rot`, `key`, `sendkey`, `shot`, `save`, `mem`, `peek`, `sample`, `fill`/`check`, `load`, `poke16`/`poke32`, `hold`). `EMU_SLOT=n` runs a second deck of the same model. `--stick`, `--kernel`. |
| `trace_set.py` + `tools/tbcov.c` | trace windows (executed TBs in first-run order); rebuild the plugin into `work/libtbcov.dylib` against `cdj-nxs2/qemu-src/include/plugins` |
| `trace_diff.py`, `align.py` | action-minus-baseline functions; 700↔MK1 alignment |
| `cave_check.py` | junk-fill write check per window (`CAVE_RUNS`, `CAVE_TAG`) |
| `remain_ocr.py` | REMAIN readout from screenshots (playhead tests) |
| `funcscan.py`, `match.py`, `coverage.py` | function lists, 700↔MK1 map, per-mod address coverage |
| `build_mk1.py`, `run_loader_mk1.py`, `unpack_mk1.py` | UPD build, loader check, unpack |
| `rgb_mk1.py` | RGB / 3-band waveform build (`build`, `script MODE`) |
| `bjswipe_mk1.py`, `bjlabels.py` | BEAT JUMP row swipe + pad labels (`build`, `emu`; `bjlabels.py check` = validation + preview); `shbuild.py` = shared sh-elf-gcc module build |
| `ksui_mk1.py`, `ksui_assets.py` | KEY SHIFT control on PERFORM (`build`, `emu`) |
| `install_mk1.py` | all mods into a running deck in a safe order (`install_all()`); `emu` = combined test |
| `phasemeter_mk1.py` | phase meter (`build`, `emu`) |
| `keyshift_mk1.py` | live key shift engine (`build`, `emu`); `ks_state()` reads the DSP code's counters over the host port. `EMU_AUDIODEV=driver=wav,path=...` records audio |
| `utility_mk1.py` | UTILITY WAVEFORM COLOR row (`build`, `emu` = qemu test incl. RGB install). MENU = touch (568,37), hold 1.5 s = UTILITY; knob = `rot N` |
| `longjump_test.py`, `longjump_edges.py`, `padlabels.py` | beat-jump presets, edge cases, pad label sprites |
| `smoke_xdj1000.py` | start.sh smoke test (PLAY, CUE, jog, touch) |
| `permanent_mk1.py emu IMG` | cold boot of a flash image (copier runs), checks copied RAM + hooks + track load |
| `MK1_JUNK=work/survey/ram_09800000.bin` | preload the deck's real mod-home RAM (junk, not zero) in `install_mk1.py emu` and `permanent_mk1.py emu` (`emu.start(paused=True)` loads it before the CPU runs) |

Saved states: `work/emu/xdj1000/*.vm` (`perform`, `main` on `work/testusb/test_usb.img`; `rgb_main` on `3band_usb.img`; `nogrid` on `nogrid_usb.img`; edge states `start`, `nearstart`, `end`, `nearend`, `loop`, `slip`). Restore with the stick they were saved with.

## xdj-mod-studio side
- Venv: `CFW/xdj-mod-studio/.venv` (numpy pillow capstone hidapi pygame).
- SH assembly: `tools/shasm.py`. C: `work/sh-tools/bin/sh-elf-gcc` 14.2.0 (built by `tools/build_sh_gcc.sh`).
- Upstream's own emulator (`emu/`, C core) runs the XDJ-700; its firmware home is in `~/Library/Application Support/XDJ Mod Studio/firmware` (incomplete: the DSP step needs `work/tic6x/objdump`).
