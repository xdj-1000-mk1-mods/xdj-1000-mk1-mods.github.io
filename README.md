# XDJ-1000 MK1 Mods

**Version 0.2.0**: what changed is in [CHANGELOG.md](CHANGELOG.md).

Mods for the **Pioneer DJ XDJ-1000 (MK1), firmware 1.13**: colour and 3-band
waveforms, a phase meter that follows the tempo master, beat-jump paging, an
optional stems mixer, all loaded **from a USB stick**.

You flash one small change to the deck: the **stick loader enabler**. After
that, every mod comes off a stick (the deck's own, or the linked player's) and
lives in RAM only. With no mods stick on the link, a power cycle gives you the
stock deck.

> **Status:** works on the authors' own XDJ-1000 MK1 (1.13) and passes the
> qemu tests (see [docs/TESTING.md](docs/TESTING.md)). This is a hobby
> project, not affiliated with Pioneer DJ / AlphaTheta. Use at your own risk.

This repo contains **no firmware**. You bring your own official
`XDJ1000.UPD` (v1.13), and everything is built from it in your browser
(or on your Mac with the command line).

## What you get

| Mod | What it does |
|---|---|
| Colour waveforms | RGB overview, centre and PERFORM waveforms. UTILITY > **WAVEFORM COLOR**: BLUE / RGB / 3-BAND. Also for tracks loaded over LINK from another player's stick |
| Mods over LINK | one mods stick is enough: a deck with the enabler takes the mods from its own stick or from the linked player's stick |
| 3-BAND from rekordbox | uses the 3-band data rekordbox already writes (`ANLZ0000.2EX`); works with any normal export |
| Phase meter | blue row = this deck, orange row = the tempo master (any player 1-6). Works for tracks loaded over LINK too. UTILITY > **PHASE METER** ON/OFF |
| Settings on the stick | WAVEFORM COLOR and PHASE METER are remembered per stick (`MODSCFG.BIN`) |
| BEAT JUMP paging | swipe the BEAT JUMP pad row on PERFORM to change jump sizes |
| Stems mixer *(optional)* | mute/solo vocals / drums / bass / other on prepared STEMS-4 tracks; needs a screenshot of your own PERFORM screen at build time ([docs/MODS.md](docs/MODS.md#stems)) |

Limits and details: [docs/MODS.md](docs/MODS.md).

## Get it (any computer, in the browser)

Open the project page, **[xdj-1000-mk1-mods.github.io](https://xdj-1000-mk1-mods.github.io/)**, and drop your
official `XDJ1000.UPD` on it. The page builds everything **inside your browser**,
uploads nothing, and only offers files that match the tested builds byte for byte:

1. `XDJ1000.UPD`: alone in the root of an empty FAT32 stick, keeping exactly that name, install once like
   an official update ([docs/FLASHING.md](docs/FLASHING.md)). Keep `XDJ1000_restore_1.16.UPD`, the way back
   (rename it to `XDJ1000.UPD` on its stick).
2. `MODSX.BIN`, `MODS.BIN`, `MODS2.BIN`: copy all three to the root of your rekordbox stick, power-cycle
   the deck and insert the stick before loading a track ([docs/STICK.md](docs/STICK.md)).

Already on the 0.1.x enabler? It keeps working with the new stick files, including colour
over LINK. Reflash only if you want decks to take the mods from another deck's stick.

The BEAT JUMP labels in the mod files are drawn from your firmware's own digits. The page does
that with the repo's Python code, run in the browser (Pyodide, about 15 MB the first time).

(The page is `index.html` + `web/`, published by GitHub Pages from `main` / root.)

## Command line (optional, macOS Apple Silicon)

For the stems mixer (it needs your own PERFORM screenshot), another default waveform, or
development, build the same files on your Mac:

```bash
git clone https://github.com/xdj-1000-mk1-mods/xdj-1000-mk1-mods.github.io.git xdj-1000-mods && cd xdj-1000-mods
brew install gmp mpfr libmpc isl hidapi        # compiler libraries + USB-B access
./xdjmod setup                                 # Python venv + SH compiler (15-30 min, once)
./xdjmod check    --upd ~/Downloads/XDJ1000.UPD
./xdjmod firmware --upd ~/Downloads/XDJ1000.UPD    # optional: same enabler + restore as the web page
./xdjmod stick    --upd ~/Downloads/XDJ1000.UPD    # -> out/stick/ (MODSX.BIN, MODS.BIN, MODS2.BIN)
./xdjmod write    --to /Volumes/MYSTICK            # your rekordbox stick
```

Each build is checked against the hashes of our tested build, and `xdjmod`
tells you if yours differs.

## Using Claude Code with this repo

The repo is set up for [Claude Code](https://claude.com/claude-code): open it
and ask, e.g. *"build the mods from ~/Downloads/XDJ1000.UPD"* or *"my phase
meter shows no ticks, help me debug"*. [CLAUDE.md](CLAUDE.md) tells Claude
the safety rules: it never flashes, writes to your stick or commits firmware
without your explicit OK.

## Docs

| | |
|---|---|
| [docs/FLASHING.md](docs/FLASHING.md) | the enabler: what it changes, installing it, going back to stock |
| [docs/STICK.md](docs/STICK.md) | stick files, settings file, troubleshooting |
| [docs/MODS.md](docs/MODS.md) | every mod, how to use it, known limits |
| [docs/SAFETY.md](docs/SAFETY.md) | what can go wrong and how to recover |
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | loader chain, file formats, memory map |
| [docs/DEVELOPING.md](docs/DEVELOPING.md) | repo layout, model table, building a new mod |
| [docs/TESTING.md](docs/TESTING.md) | the qemu tests, and running them yourself |

## Credits and license

MIT ([LICENSE](LICENSE)). Built on **XDJ Mod Studio** (the XDJ-700 mods, MIT,
[LICENSE.upstream](LICENSE.upstream)), whose mod sources (`src/tools/`) this
port compiles for the MK1 with MK1 addresses. Tested with
[cdj-nxs2-qemu](https://github.com/Stijn-Jacobs/cdj-nxs2-qemu) (GPL-2.0, not
included). Pioneer DJ, rekordbox and XDJ are trademarks of AlphaTheta Corporation.
