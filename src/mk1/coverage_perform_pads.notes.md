## Deferred (paused 2026-11-01 for the MK1 long-beat-jump target)

The six items step 3 asked for are mapped and verified in the emulator (rows marked
`traced/...` above; evidence in `mk1/traced_map.json`). Left to do, none of it needed
for the long beat jump:

- **XDJ-700 trace set** (`mk1/trace_set.py xdj700`): 11 of 25 windows were recorded on
  QEMU 9.1. Recreate the 700's saved states on QEMU 11 (`work/emu/xdj700/*.vm` no
  longer load), then record all 25 windows.
- **`mk1/align.py`**: line up 700 and MK1 action traces (needs the 700 set). Expected to
  map the remaining touch-path and PERFORM-draw functions; candidates by trace order
  only, so everything it proposes starts as unverified.
- **PLAYW `0x0B6C4264` -> `0x0E0C4228`** (80/81 literal votes, 1 dissent) and the
  **PERFORM mode word `0x0BA371D4` -> `0x0E437288`** (52/52): sample both on MK1
  while playing/paused and on/off the PERFORM screen (expect 5 = playing and 7 = PERFORM,
  as the 700 code assumes).
- **MK1 re-record** of the full 25-window trace set with the ordered plugin (QEMU 11).
- **Key bitmap KEY93/KEY94** (`0x0E0C7A3D/3E`, unverified): find the mod's real trigger
  timing (it re-asserts the bit inside the touch hook) before testing.
- Not mapped at all yet: the 2DG draw path beyond the flush hook (pad art, fonts),
  `0x080B7D20`'s neighbours that perform_pads reads, and the GUI addresses in
  `mysettings.py` / `vredirect.py` that perform_pads imports.

**Model constants that differ (go in the model table, never inline):** touch "no zone"
0x1E (700) vs 0x23 (MK1); MK1 hot-cue row 0x1E, beat-jump pad 0x16; 700 hot-cue row 0x19.

**UI note:** MK1 already has native BEAT JUMP pads on PERFORM (<<1 >>1 <<2 >>2 <<4 >>4).
perform_pads' beat-jump half is redundant on MK1; what MK1 lacks is the 700's BEAT LOOP
row and the mod's paging/KEY/STEMS. The pads themselves would need re-laying out.
