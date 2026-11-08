# Phase meter (MK1 v1.13)

Upstream `tools/phasemeter/pm.c` + `pmhook.S` + shipped `pm_label.h`, built by `phasemeter_mk1.py` with only
the model addresses swapped (one exact match each). Replaces the stock 4-box "Bars" rows above the centre
waveform (main screen and PERFORM, 103 px higher) with two scrolling beat rulers: orange = master (MK1
addition, see below), blue = this deck, grey ticks = beats, red = downbeats, +-4 beats around a white "now" line at the
playhead. Runs on every display flush (chained on the flush hook); strips the stock meter's repaint commands.

## Mapping (model table)
| 700 | MK1 | evidence |
|---|---|---|
| mode word 0x0ba371d4 | 0x0e437288 | `screen_mode_word` (sampled 1/7; BROWSE 2) |
| ANLZ ctx 0x09826be4, PQTZ +0xd7c | 0x0c226be4, +0xd7c | `beat_grid`: same header, 179 beats, 499 ms apart |
| POSL 0x0c0e6d18 (1/150 s) | **0x0eae6dbc** | `play_position`: same writer function as the 700's hardware-verified word (see below); deck read still pending |
| preview 0x0ba3bccc | 0x0e43bd80 | RGB build |
| flush hook | 0x08c37f14 / 0x08e23578 | `flush_hook` (now exercised) |
| geometry | identical | `phasemeter_geometry` (screenshots) |
MSOFF / TS_DATA (MY SETTINGS, theme switcher: not on MK1) point at zero words at the module's end.
Module 6.9 KB + 20 KB state at 0x098c0000 (`phasemeter_module`, unverified RAM).

## qemu test (`phasemeter_mk1.py emu`, state `perform`, paused): PASS 10/10
Grid snapshot 179/179 beats. Every visible tick (8 per view) and downbeat sits where pm.c's own formula puts
it for the paused position, on PERFORM, after 3 s more play, and on the main screen; now line and blue row
drawn; stock boxes gone (179 repaints stripped). BROWSE: no drawing; back on main: drawing again. 0 rejects.
Shots: `work/pm/shots/`, side by side `work/pm/compare.png`.

## Position word: emulator vs hardware (2026-11-01)
Upstream's emulator used a stand-in audio chip that advanced the wrong word; on a real 700 the live one is
0x0c0e6d18 (+4 = length). cdj-nxs2 runs the real audio-chip program and reproduces that hardware reading on
the 700 (0x0c0e6d18 follows REMAIN, 0x0c0e6d1c = 13500 = length). On both models the word is written by the
same function (85.7% aligned; the alignment pairs the 700 store 0x08dc9c4c with MK1 0x08d70904, both
`mov.l Rx,@(4,r5)` into the same 5-field struct). MK1's second copy 0x0eae6c28 is derived from it.
Remaining: two reads on the deck while playing (read-only survey).

## Not verified
- Linked decks (master row, the stock meter's link repaints), MENU popup overlap, no-track state.

## On/off: UTILITY > PHASE METER (OFF / ON)
Row in `utility/ut_mk1.c`, writes `pm_mode` (0 = stock meter, 1 = Type 1). Shows NOT INSTALLED (no edit)
unless the meter module is in RAM (its entry literal = pm_hook's address). `install_mk1.py emu`: OFF stops
drawing and the stock meter comes back; ON draws again, ticks exact.

## Install order with key shift (`install_mk1.py`)
Both use the flush hook. Either order works; what must not happen is re-hooking while key shift's one-shot
is pending (ksh.c then sees it is not the head of the chain, gives up with status 3, never installs).
`keyshift_mk1.install()` returns only after the one-shot has reported and released the hook. Tested the
harder order (meter first): key shift status 1, hook handed back to the meter, shifting with the meter
chained, meter still exact. (Earlier note in this file had the order backwards.)

## Master row (MK1 addition, 2026-11-01)
Upstream left the orange row a dim line. `phasemeter_mk1.master_row()` patches our build copy of pm.c (upstream
untouched): if the other linked player has the master flag (status 0x0d2d04f0 +0x09 bit 0x20), the orange row
draws its beats: beat-in-bar from 0x0d2be62f (changes on the beat, beat packets), fraction = (ms clock 0x0dae5cdc
- time of the last change) / beat length from BPM*100 (+0x10) x pitch (+0x0c, 0x100000 = 0%); otherwise this deck
is master and the orange row mirrors its own beats. Addresses: models `link_master`, `ms_clock`.
qemu (no link possible): regression 10/10, orange mirrors blue. **Deck 2026-11-01: works (user), both roles.**
Limits: 2 decks only (3+ players: other slots not read); timing follows the beat packet's arrival.
