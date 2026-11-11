# XDJ-1000 MK1 Mods: notes for Claude

This repo builds mods for the Pioneer DJ XDJ-1000 **MK1, firmware 1.13** from the
user's own official `XDJ1000.UPD`. Start with README.md; the details are in docs/.

## Safety rules (always)
1. **Never flash a deck, write to a USB stick, or send anything to a deck without the
   user's explicit OK for that specific action.**
   - `./xdjmod write` and `deck_write.py ... --go` write; ask first.
   - Read-only commands are fine: `./xdjmod deck-status`, `deck_write.py loader-status` / `pm-status`.
   - Don't add `--yes` to `xdjmod write` unless the user asked for it.
2. **Never commit or publish firmware or anything derived from it:**
   - `.UPD` files and decoded `*.img` images;
   - `MODS*.BIN`, qemu `*.vm` states, RAM dumps;
   - screenshots of the deck's screens.
   Check `git status` before any commit. Everything generated lives in `src/work/` and `out/`.
3. Only the official v1.13 file is supported (`xdjmod check`). Other versions or decks
   (XDJ-1000MK2, XDJ-700) are refused on purpose: their addresses differ.
4. If `xdjmod` says an output is **NOT the tested build**, tell the user not to flash or
   use it, and investigate before anything else.
5. If you're unsure whether something could brick the deck or damage the user's stick,
   stop and ask.

## Common tasks
| User wants | Do |
|---|---|
| First setup | `./xdjmod setup` (it needs `brew install gmp mpfr libmpc isl hidapi`; the compiler build takes 15-30 min) |
| Build everything | `./xdjmod check --upd F`, then `./xdjmod firmware --upd F` and `./xdjmod stick --upd F` |
| Put the mods on a stick | confirm the volume with the user, then `./xdjmod write --to /Volumes/X` |
| Get the files | the GitHub Pages site (`index.html` + `web/`: enabler v2, restore, MODSX.BIN, MODS.BIN, MODS2.BIN, built in the browser) or `./xdjmod firmware` / `./xdjmod stick`; the user installs the enabler like an official update (docs/FLASHING.md). You don't. |
| Back to stock | `out/XDJ1000_restore_1.16.UPD`, installed by the user (docs/FLASHING.md) |
| Debug "mods don't appear" / phase meter / 3-band | ask for `./xdjmod deck-status` output (deck on USB-B), then use docs/STICK.md#troubleshooting |
| Stems | docs/MODS.md#stems; it needs `--stems-screenshot` (emulator, docs/TESTING.md) |

## Working on the code
- `web/core.js` must stay byte-exact with the Python build: run `node web/test.mjs <UPD>` after any change.
  `web/patch.json` and `web/stick.json` hold only our bytes; regenerate them with `web/make_patch.py`, never by hand.
  Keep its hot loops free of closures that change captured variables: V8 produced wrong bytes with them.
- Read docs/DEVELOPING.md first. Every firmware address goes in
  `src/mk1/models/xdj1000_113.json` with evidence, and guesses are marked `"unverified": true`.
- Test order: qemu (docs/TESTING.md), then read-only on the deck, then a stick on the deck.
- `src/mk1/loader/ldr.c` builds three loaders: the first enabler's (plain), the stick-side one
  (`CFG_NAME`) and enabler v2's loader X (`LINK_SET_STOCK`). The two flashed ones must not change
  casually: every user would have to reflash. The build refuses if the first one changes; for
  loader X compare the enabler hash in `xdjmod` / `web/patch.json`.
- Long builds and emulator runs: start them in the background, log to `src/work/logs/`,
  and read only the tail.
