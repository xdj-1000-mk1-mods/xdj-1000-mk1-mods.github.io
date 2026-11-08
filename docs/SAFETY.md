# Safety

## What is flashed, and what isn't

| | Persistent? | Goes back to stock by |
|---|---|---|
| Enabler UPD | yes, in the deck's flash | installing the restore UPD ([FLASHING.md](FLASHING.md#going-back-to-stock)) |
| Mods from `MODS.BIN` / `MODS2.BIN` | no, RAM only | power-off |
| `MODSCFG.BIN` | on the stick | deleting the file |

## Built-in safeguards
- **Input file:** only the official XDJ-1000 v1.13 update (SHA-256) is accepted.
- **Enabler build:** it must decode back to exactly the intended image; the boot stub,
  updater block and panel firmware must be byte-identical to stock; and it's compared
  with the tested build's hash.
- **Stick loader:**
  - checks the whole file first (header, CRC32, every address, and every hooked word
    still stock) and writes nothing on any error;
  - writes only into a free RAM area;
  - installs only with no track loaded, and at most once per power-on.
- **Hooks:** each one is a single aligned 32-bit store, done last, after the code it
  points to is in place.

## Real risks
- **Flashing itself.** As with any firmware update, power loss during an update is the
  main risk. The enabler leaves the updater block (flash block 0) untouched.
- **A mod bug while playing:** a frozen screen or a crash, and the deck needs a power
  cycle. Test at home before a gig.
- **Settings write:** the deck writes 20 bytes to your stick when a setting has changed.
  Pulling the stick during that moment can damage that file, or in the worst case the
  stick's file system, as with any device that writes. Keep a copy of your rekordbox
  export.
- **Untested on hardware:** the 1.16 restore over the enabler, decks other than the
  XDJ-1000 MK1 on 1.13 (they're refused anyway), and a DJM or rekordbox in the link.

## Rules for contributors (and for Claude)
- Never commit firmware, decoded images, built UPDs, stick files, RAM dumps or
  screenshots of the deck (`.gitignore` covers the usual names).
- Every firmware address or constant goes in `src/mk1/models/xdj1000_113.json`, with
  evidence. Mark guesses `"unverified": true`.
- qemu before hardware, and read-only before writing.
- Don't change the stick loader in the flashed enabler casually: changed code means a
  new enabler, and every user has to reflash. `mods_all.py` refuses to build if loader1
  differs from the flashed one.
