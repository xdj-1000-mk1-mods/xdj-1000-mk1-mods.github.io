# UTILITY WAVEFORM COLOR row (MK1 v1.13)

Port of upstream `tools/utility.py` + `tools/utility/ut.c`, reduced to the WAVEFORM COLOR row
(BLUE / RGB / 3-BAND). The row writes the RGB mod's mode byte (`work/rgb/build/install.json` mode_addr).
Files: `utility_mk1.py`, `utility/ut_mk1.c`, `utility/utentry.S`. Addresses: model table entries
`utility_table` (both models) and `utility_module` (MK1, unverified free RAM).

| item | 700 v1.15 | MK1 v1.13 | evidence |
|---|---|---|---|
| image table (16 x 52 B) | 0x08e634b4 | 0x08e097bc | CB_DRAW word unique in both; fields equal in all 16 rows; 52 callback pairs map 1:1 |
| RAM table | 0x0e736410 | 0x14135ab4 | pool loaded by mapped user 0x08d79236 (same code as 700 0x08dd257e) |
| count | 0x0e736750 | 0x14135df4 | = table + 0x340, adjacent to 3 of the pools on both |
| pools | 0x08dd23f4 272c 2a58 2aec | 0x08d790a8 793e4 79710 797a4 | the only 4 words = RAM table |
| callbacks nop/draw/begin/sel/q0/end | 0x08dd0c6a ... | 0x08d77932 0x08d77936 0x08d78654 0x08d78798 0x08d78d58 0x08d78d9a | record-by-record pairing |

Module: 1236 B at 0x09804000 (+ 8 B bss counters to 0x098044dc; zero before install).
Install: RGB build, module, 4 pools -> copy (0x09804160), then count 16 -> 17. Revert: count first.

## qemu test (`utility_mk1.py emu`, from `rgb_main` on `3band_usb.img`): PASS
RAM table matches image; count/pools stock; area empty; row drawn at the end of UTILITY (after VERSION No.);
RGB -> 3-BAND -> BLUE -> RGB each changes the mode byte and the overview waveform; push/push without a turn
does not commit; pools/count intact on exit; deck running. Shots: `work/utility/shots/`.

Note: the stock value editor clamps at the ends (no wrap): from 3-BAND, turning right stays on 3-BAND.
Not yet tested: centre waveform redraw after a switch, UTILITY with no track loaded, PERFORM screen.
