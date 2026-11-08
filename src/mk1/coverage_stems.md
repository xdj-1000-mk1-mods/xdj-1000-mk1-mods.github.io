# Live stems (MK1 v1.13): step A, the mixer

Upstream `tools/stems/sm.c` + `smhook.S` (XDJ-700, hardware-tested: "mutes heard after ~30 s"), built by
`stems_mk1.py` with only model constants swapped (models `stems_io`, `stems_module`):

| 700 | MK1 | evidence |
|---|---|---|
| FREAD 0x08C61A6C | 0x08c06b60 | 40/40 masked instructions identical; 0x13B0 below fseek as on the 700 |
| FSEEK3 0x08C62E1C | 0x08c07f10 | function map (sig, high) |
| audio-read pool 0x08D5FFA8 | 0x08d06c98 | 5 pools -> fread in both images, same mapped functions, same order |
| DIRECT slot 0x08DDFFD4 | 0x08d86bb4 | same, and fn + 0x9a in both |
| home 0x09836000 | 0x09850000-0x09880000 | upstream's home is RGB SNAP on MK1; deck-surveyed free |
| PMASK (perform_pads) | 0x0987fff0 | MK1 has no STEMS pads yet; V_* (700 version switcher) = zero words after it |

**DSP 'faster mute' path OFF on MK1** (`dr_on = 0`): it writes the decoded audio in the DSP's DDR at 700 DSP
addresses (ring 0xC0090000, playhead 0x11837CCC), unverified on MK1, and writing the running audio chip needs
the user's OK. The SH-RAM re-mix of buffered reads stays on.

Both the pool and the DIRECT slot are routed to the mixer (upstream found on hardware that the real reads come
through DIRECT; in qemu with only the pool hooked, 3 of 12 buffers stayed unmixed).

## qemu test (`stems_mk1.py emu MASK`, cold boot, stick = test stick with its track replaced by a 4-tone STEMS-4 WAV)
Exact check: the bytes each sampled read left in the deck's buffer == the expected stem sum for that file position.
mask 0b0101: 12/12, mask 0 (pass-through == plain mix): 12/12, mask 0b1110: 12/12. File recognised, ~2,600 reads
mixed per run. qemu's audio output is silent (no playback audio), so no listening test.

## Step B: STEMS control on PERFORM (`stemsui_mk1.py`, `stemsui/stemsui.c`, artwork `stemsui_assets.py`)
Tap the BEAT JUMP row label (HOT CUE's label is the KEY SHIFT control) -> the row becomes
STEMS [VOCALS] [DRUMS] [BASS] [OTHER] [ALL ON] [BACK]: a stem pad toggles its PMASK bit (white = on, dim = muted),
ALL ON clears the mask, BACK or the label closes. Mutes stay when closed; the label then reads STEMS in red.
Inert unless the mixer is installed (entry table at 0x09850000 names sm_fread): the label tap then goes to stock.
Pads = the stock BEAT JUMP pads with the tab arrows filled and the digit band rebuilt. Module 0x098e0000 (1,128 B),
images 0x098e0800 (101,824 B). Hooks: display flush + touch, chained like the KEY SHIFT control; installed after the
BEAT JUMP swipe and the mixer (touch order: STEMS UI -> swipe -> stock).

qemu (`stemsui_mk1.py emu`, stems test stick, track playing on PERFORM): PASS. Pads/title pixel-exact (1.000);
VOCALS + BASS -> mask 0b0101; **mute during play**: 1 re-mix, and after the deck's next read 8/8 sampled buffers
== the new mix (right after a tap the newest buffer still holds the previous mask's mix until the next read call);
ALL ON -> 0; DRUMS + BACK -> closed, mask kept, red STEMS label, row == stock; BEAT JUMP pads still reach the swipe.

## Open
- Step C: `deck_write.py stems` (mixer: pool + DIRECT, stock-checked; STEMS UI: flush + touch chain) and STEMS-4
  files from the Mac (`tools/stems4.py`, needs separated stems, e.g. Demucs).
- On the deck a mute is heard after the deck's read-ahead (upstream's 700: ~30 s); the DSP faster-mute stays off.
