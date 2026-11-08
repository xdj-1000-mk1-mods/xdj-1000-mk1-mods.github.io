# Live key shift (MK1 v1.13): engine + PERFORM control

Upstream: `tools/keyshift_hot_apply.py`, `tools/keyshift_dsp/ksh.c` + `kshhook.S` (SH installer),
`ks.c` (DSP code, prebuilt v3 `prebuilt/deck/keyshift/ks.bin`). Beta upstream; a real-deck
"freeze + file corrupted" report is still open there. Port: `keyshift_mk1.py`.

How it works: with MASTER TEMPO on, the DSP's time-stretcher pulls frames through a "block puller";
ks.c wraps that call, resamples the staging frames by k and runs the stretcher at speed/k, so pitch x k
and tempo unchanged. k comes from the key word (SH writes, DSP mailbox 0x11837bd8):
`0x40000000 | round(2^(s/12) * 2^20)`, `0x00100000` = off. The installer runs once from the display-flush
hook with no track loaded, checks the DSP program over the host port, writes the code to loader padding
(DSP 0xc005f4c0), reads it back, re-points 4 stretcher loads, flips one call word, unhooks itself.
Then the deck's own store into the key word (0x08cdd630, `mov.l r1,@(20,r12)`) is NOPed.

## Mapping (model table: dsp_image, keyshift_dsp, key_word, track_len_word, host_port, flush_hook, master_tempo_word)
- DSP program: same SH address/length as the 700; every word ks.c/ksh.c checks or patches is identical,
  and the data addresses are built by identical mvk/mvkh pairs at identical offsets. ks.bin runs unchanged.
- SH: only 2 constants differ from the 700: flush slot 0x08c37f14 (stock 0x08e23578) and the
  track-loaded word 0x0e43c104. Key word 0x0c724dd8, store site 0x08cdd630, HPI regs identical literals.
- MASTER TEMPO byte 0x0e0c419c verified (panel 0x15/0x10 toggles it 0/1).

## qemu test (`keyshift_mk1.py emu`, fresh boot, test stick, MT on): PASS 19/19
Install status 1 (DSP program verified, landing = FF padding, call word read back). Key 0/+4/-4/+6/-6/0,
read from the DSP code's own counters over the host port: k latched exactly (1.2599, 0.7937, 1.4142,
0.7071), every block shifted, 0 clamps; key 0 = pass-through; the key word holds; deck keeps running.
Tempo: ~16 original frames are consumed per 16-sample output block, so the playhead runs at normal speed.

## Not verified
- **Audio**: qemu's emulated DSP manages ~753 blocks/s while shifting vs the ~800/s it needs (and does
  unshifted), so the recording (`work/keyshift/ks_emu.wav`) has gaps; pitch could not be measured from
  it. The DSP is identical to the 700's, where upstream checked pitch in their emulator and on a deck (v1).
- Revert (`KSH0`), MT off -> key -> MT on (upstream's freeze; the UI must reset the key on any MT change),
  track reload restoring the key, linked decks.

## PERFORM control (`ksui_mk1.py`, `ksui/ksui.c`, art `ksui_assets.py`)
Tap the HOT CUE row label (PERFORM): the row becomes KEY SHIFT [ - ] [ key ] [ + ] [ RESET ] [ BACK ];
BACK or the label again = hot cues. Upstream rules kept: inert unless the engine is installed (value pad N/A)
and MASTER TEMPO is on (value pad MT OFF); any MT change resets the key to 0; the key is put back when the
deck clears the word (track load). Flush hook draws the pads over the row on every full-screen present
(the deck re-blits its own pads, so BACK shows them again); touch hook chained in front of the beat-jump swipe.
Art: the stock pads with the text band rebuilt from each row's 4-px texture, Helvetica Neue Bold at the
stock cap heights. Module 1.4 KB at 0x098d0000, images 232 KB at 0x09920000 (`ksui_module`, unverified RAM).

qemu test (`ksui_mk1.py emu`, fresh boot, all mods via install_mk1): every screen pad equals its image
(1.000 of pixels within 8/255) for MT OFF, +2, -1, +1; +/-/RESET step the key word; DSP latched k 1.1225 at +2;
+ inert with MT off; MT change resets (key 0, word 0x00100000); a cleared word is put back; BACK = stock row
again (1.000 like before); main screen: neither the row nor the label spot is taken.
Not tested: pads light when pressed (they don't), linked decks, track with hot cues stored (the deck's
coloured cue pads are simply painted over while in KEY SHIFT).
