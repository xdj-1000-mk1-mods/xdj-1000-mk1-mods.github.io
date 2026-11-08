# BEAT JUMP row swipe (MK1 v1.13)

The XDJ-700 mod's paging (upstream `tools/perform_pads.py`): tap a pad = jump; drag the row > 48 px =
next/previous size page, one step per drag, left = bigger: 1-2-4 -> 4-8-16 -> 16-32-64.
On MK1 the pads are stock, so only the touch handling is new. Files: `bjswipe_mk1.py`,
`bjswipe/bjswipe.c`, `bjswipe/bjentry.S`, `shbuild.py` (shared with `utility_mk1.py`).

How: the hit-tester slot (`touch_hook.slot` 0x08cf94f4) -> `bj_entry`. Stock fires the jump on PRESS
(FWTRACE, `touch_hook.jump_timing`), so a new press inside `bj_pad_rects` on PERFORM
(`screen_mode_word` == 7) is held back from stock. A drag rewrites the beats of the six `bj_table`
entries (uncached alias, directions untouched). A release with no drag calls `bj_handler(code)`, so the
stock guards and quantize apply. Every other touch goes to the stock hit-tester unchanged.
Module 602 B + bss at 0x09806000..0x098062f8; labels 224,640 B at 0x09880000 (`bjswipe_labels`). Install: zero bss, load, slot (one store). Revert: slot, then page 0.

## Pad labels (`bjlabels.py`)
Each page change also copies that page's digit bands (rows 20..45 of all 18 sprites: 6 pads x normal/lit/dim)
into the stock sprites via the uncached alias; the PERFORM screen re-blits them by itself (poking a sprite
changed the screen within 2 s with no input). Page 0 is the stock bytes, so paging back restores stock exactly.
Rendering: background per row rebuilt from its <= 4 px period (same on all pads in the band); digit masks
from the firmware sprites (1/2/4 BEAT JUMP, 8 and 6 from BEAT LOOP 8/16), one mask set for all styles
(stock alpha differs <= 0.11 between styles). Check: stock 1/2/4 re-rendered match stock within 6/63 (green).
**The 3 is synthetic** (no sprite has one): the firmware 8 with its left side cut (`glyph3()`).
Replaces `padlabels.py`'s transplant (left the old digit's edges; kept as a record).

## qemu test (`bjswipe_mk1.py emu`, state `perform`, paused, 120.2 BPM): PASS, 21/21
Jumps read off REMAIN: page 0 <<1 +0.500 / >>1 -0.500 / <<4 +1.993 s; page 1 <<8 +3.993 / >>8 -3.993;
page 2 <<16 +7.986 / >>16 -7.986 (want n x 0.499 s). Swipe: no jump (0.000 s); clamps at both ends.
The hook gets y in screen px. Labels: sprite RAM == page bands (all styles) and the screen pads match them (1.000 of pixels within 8/255, cols 0-77) on pages 0, 1, 2 and back to 0. QUANTIZE still toggles through stock. On the main screen nothing is taken.

## qemu test while playing (`bjswipe_mk1.py emu-play`, state `perform`, playing, 120.2 BPM): PASS, 18/18
Jumps read off the play-position word (1/150 s) minus the playback in between (rate 0.999):
1 +0.506/-0.508, 8 +3.996/-3.987, 32 +15.975/-15.968, 64 back -31.945 at 37 s, **64 forward +31.956 (not refused while playing)**
(want n x 0.499 s). Swipes while playing page without a jump; back to page 0 restores the table.
<< 64 with only 24 s behind: refused (+0.008 s, stock). play_state reads 3 while playing in qemu too (= the deck).

## Known limits
- The 3 in 32 is synthetic (see above): check it by eye on the deck. No separate page indicator (the labels show the sizes).
- Labels persist while off PERFORM; a reboot restores stock (RAM only). No uninstall by design (user 2026-11-01):
  a reboot is the way back to stock.
- Pads no longer light while pressed (stock never sees the press). The jump comes on release, not on press.
- 32/64: verified while playing (above). Paused, forward > ~46 beats is refused by stock (long-jump test); playing, 64 forward works.
- Untested: PERFORM with no track loaded, multi-touch, a drag that leaves the row.
