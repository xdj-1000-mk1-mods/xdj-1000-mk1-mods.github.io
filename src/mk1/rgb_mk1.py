#!/usr/bin/env python3
"""RGB / 3-band OVERVIEW waveform for MK1 v1.13, built from upstream's own code.

tools/rgb_overview.py (the overview cave) and tools/rgb_detail.py (COPY5, the
snapshot routine the cave calls) are executed from their source with ONLY
their model-specific constant lines replaced; every other line, including
the SH assembly, is upstream's. Replacements come from
mk1/models/xdj1000_113.json, and each one must match the original line
exactly once (else the build stops: upstream changed under us).

Layout (MK1 RAM home, see the model table's ram_home_candidate):
    CAVE  = HOME            overview cave (+0x580 RECIP, +0x7F0 MODE byte)
    COPY5 = CAVE + 0x2900   snapshot routine (upstream offset)
    SNAP  = HOME + 0x10000  SLOT4 | SLOT6 | SNAP_HASH | SLOT5 (0x40000)

    usage: python3 mk1/rgb_mk1.py build      -> work/rgb/build/*.bin + install.json
"""
import json
import os
import re
import struct
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
MODEL = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))
E = MODEL["entries"]
HOME = int(os.environ.get("RGB_HOME", E["ram_home_candidate"]["addr"]), 0)
OUT = os.path.join(ROOT, "work", "rgb", "build")


def _sub(src, old, new):
    if src.count(old) != 1:
        raise SystemExit(f"rgb_mk1: expected exactly one {old!r} in upstream source")
    return src.replace(old, new)


def load_upstream():
    os.environ["CAVE"] = hex(HOME)
    os.environ["SNAP"] = hex(HOME + 0x10000)
    sys.path[:0] = [ROOT, TOOLS]
    ov, ctx = E["overview_painter"], E["anlz_ctx_table"]
    src = open(os.path.join(TOOLS, "rgb_overview.py")).read()
    src = _sub(src, "HOOK_POOL = 0x08DBC5C8", "HOOK_POOL = %s" % ov["release_slot"])
    src = _sub(src, "ORIG_RELEASE = 0x08C2C984", "ORIG_RELEASE = %s" % ov["release_fn"])
    src = _sub(src, "CTX_TAB = 0x09826BE4", "CTX_TAB = %s" % ctx["addr"])
    src = _sub(src, "IDX_OFF = 0x13B8", "IDX_OFF = %s" % ctx["extra_index_off"])
    ro = types.ModuleType("rgb_overview")
    ro.__file__ = os.path.join(TOOLS, "rgb_overview.py")
    sys.modules["rgb_overview"] = ro
    exec(compile(src, ro.__file__, "exec"), ro.__dict__)
    dsrc = open(os.path.join(TOOLS, "rgb_detail.py")).read()
    dsrc = _sub(dsrc, "PREVIEW = 0x0BA3BCCC", "PREVIEW = %s" % ov["preview"])
    ce = E["centre_painter"]
    dsrc = _sub(dsrc, "POOL = 0x08DC3D94", "POOL = %s" % ce["palette_slot"])
    dsrc = _sub(dsrc, "PALETTE = 0x0E736150           # stock value of POOL",
                "PALETTE = %s           # stock value of POOL" % ce["palette"])
    dsrc = _sub(dsrc, "INSN = 0x08DC3B86", "INSN = %s" % ce["colour_fetch"])
    dsrc = _sub(dsrc, "SLOT7 = 0x098B0000", "SLOT7 = %#x" % (HOME + 0x100000))
    dsrc = _sub(dsrc, "ROWINC = (0x08DC3B9E, 0x6291, 0x6295)", "ROWINC = (%s, 0x6291, 0x6295)" % ce["row_load"])
    dsrc = _sub(dsrc, "POOL2, PALETTE2 = 0x08DC2A18, 0x0E735FA8",
                "POOL2, PALETTE2 = %s, %s" % (ce["twin_palette_slot"], ce["twin_palette"]))
    dsrc = _sub(dsrc, "INSN2 = 0x08DC292A", "INSN2 = %s" % ce["twin_colour_fetch"])
    dsrc = _sub(dsrc, "ROWINC2 = (0x08DC2946, 0x6291, 0x6295)", "ROWINC2 = (%s, 0x6291, 0x6295)" % ce["twin_row_load"])
    os.environ["CW_BASE"] = hex(HOME + 0x8000)
    rd = types.ModuleType("rgb_detail")
    rd.__file__ = os.path.join(TOOLS, "rgb_detail.py")
    sys.modules["rgb_detail"] = rd
    exec(compile(dsrc, rd.__file__, "exec"), rd.__dict__)
    return ro, rd


LINK_GUARD = r"""
/* MK1 port addition (2026-11-10, user reports): the colour snapshots come from
 * the USB slot's ANLZ context, which a track loaded over Pro DJ Link never
 * fills: it still holds the last track loaded from this deck's own stick, and
 * that track's colour waveform was shown for the LINK track. Guard: the deck's
 * own beat-grid table (models deck_grid, filled for USB and LINK loads) must
 * match the context's PQTZ (models beat_grid). If not, the colour slots are
 * emptied (stock blue waveform). Re-checked only when the deck side changes
 * (new track: snapshot hash; grid landed: table signature), never because the
 * context changed (another deck loading from this deck's stick). If the
 * colour was emptied and the track then matches (a local load whose grid
 * landed late), the overview snapshot is forced to run again. */
static u32 last_g, emptied;
u32 cw_guard_same, cw_guard_empty;                       /* test probes */

static u32 dg_sig(void)
{
    return (R32(DG_VALID) * 0x9E3779B1u) ^ (R32(DG_COUNT) * 0x85EBCA77u)
        ^ (R32(DG_ENTRIES) * 0xC2B2AE3Du) ^ R32(DG_ENTRIES + 4);
}

static int same_track(void)
{
    u32 ctx = R32(CTX_TAB);
    if (!ok_ptr(ctx, PQTZ_OFF + 0x1C) || R32(DG_VALID) != 1u) return 0;
    u32 q = ctx + PQTZ_OFF, n = R32(DG_COUNT);
    if (R32(q) != TAG_PQTZ || R32(q + 0x10) != 8u || R32(q + 0x14) != n || n < 2) return 0;
    u32 ep = R32(q + 0x18), k = n < 8 ? n : 8;
    if (!ok_ptr(ep, 8 * k)) return 0;
    for (u32 i = 0; i < k; i++) {
        const volatile u8 *e = (const volatile u8 *)(ep + 8 * i);
        u32 ms = e[4] | e[5] << 8 | e[6] << 16 | (u32)e[7] << 24;
        if (ms != R32(DG_ENTRIES + 8 * i) || e[0] != R32(DG_ENTRIES + 8 * i + 4)) return 0;
    }
    return 1;
}

static void guard(u32 h)
{
    if (same_track()) {
        cw_guard_same++;
        if (emptied) {                                   /* colour back: rerun the overview snapshot */
            emptied = 0;
            R32(SNAP_HASH) = h ^ 0x5A5A5A5Au;
        }
        snap7();
    } else {
        cw_guard_empty++;
        emptied = 1;
        R32(SLOT4) = 0; R32(SLOT5) = 0; R32(SLOT6) = 0; R32(SLOT7) = 0;
        k7 = 0;
    }
}
"""


def link_guard(src):
    """MK1: show the stock blue waveform, not another track's colours, when the
    USB context does not hold the loaded track (LINK loads). See LINK_GUARD."""
    old_head = "static u32 col(u32 idx8, u32 step, u32 white, u32 rmax, u32 pal)\n{"
    old_snap = ("    u32 h = R32(SNAP_HASH);\n    if (h != last_hash) {                             /* new track loaded */\n"
                "        last_hash = h;\n        snap7();\n    }\n")
    new_snap = ("    u32 h = R32(SNAP_HASH), g = dg_sig();\n    if (h != last_hash || g != last_g) {     /* new track / grid landed */\n"
                "        last_hash = h;\n        last_g = g;\n        guard(h);\n    }\n")
    src = _sub(src, old_snap, new_snap)
    i = src.index("u32 cw_col(u32 idx8, u32 step, u32 white)")
    return src[:i] + LINK_GUARD + "\n" + src[i:]


def cw_build_mk1(ro, rd):
    """tools/centre/cw.c compiled for MK1: a generated copy with the two stock
    palette #defines swapped, the same flags as tools/centre/build.sh."""
    import subprocess
    ce = E["centre_painter"]
    src = open(os.path.join(TOOLS, "centre", "cw.c")).read()
    src = _sub(src, "#define PALETTE 0x0E736150u", "#define PALETTE %su" % ce["palette"])
    src = _sub(src, "#define PALETTE2 0x0E735FA8u", "#define PALETTE2 %su" % ce["twin_palette"])
    src = link_guard(src)
    d = os.path.join(OUT, "centre")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "cw_mk1.c"), "w").write(src)
    SH = os.path.join(ROOT, "work", "sh-tools", "bin")
    g, bg = E["deck_grid"], E["beat_grid"]
    D = dict(MODE_ADDR=ro.MODE_ADDR, SLOT5=ro.SLOT5, SNAP_HASH=ro.SNAP_HASH, CTX_TAB=ro.CTX_TAB,
             IDX_OFF=ro.IDX_OFF, TAG_PWV5=rd.TAG_PWV5, TAG_PWV7=rd.TAG_PWV7, SLOT7=rd.SLOT7,
             SLOT7_MAX=rd.SLOT7_MAX, SLOT4=ro.SLOT4, SLOT6=ro.SLOT6,
             PQTZ_OFF=int(bg["ctx_off"], 16), TAG_PQTZ=int(bg["tag"], 16),
             DG_VALID=int(g["valid"], 16), DG_COUNT=int(g["count"], 16), DG_ENTRIES=int(g["entries"], 16))
    elf = os.path.join(d, "cw.elf")
    subprocess.run([os.path.join(SH, "sh-elf-gcc"), "-m4-nofpu", "-mdiv=call-div1", "-ml", "-O2", "-Wall",
                    "-ffreestanding", "-fno-builtin"] + ["-D%s=%#xu" % kv for kv in D.items()] +
                   ["-ffunction-sections", "-fdata-sections", "-nostdlib", "-Wl,--gc-sections",
                    "-Wl,-e,_cw_col", "-Wl,-u,_cw_col2", "-Wl,-Ttext=%#x" % rd.CW_BASE,
                    "-o", elf, os.path.join(d, "cw_mk1.c"), "-lgcc"], check=True)
    binf = os.path.join(d, "cw.bin")
    subprocess.run([os.path.join(SH, "sh-elf-objcopy"), "-O", "binary", "-j", ".text", "-j", ".rodata",
                    "-j", ".data", elf, binf], check=True)
    nm = subprocess.run([os.path.join(SH, "sh-elf-nm"), elf], capture_output=True, text=True, check=True).stdout
    syms = {}
    for ln in nm.splitlines():
        a, _, n = ln.split()
        if n.startswith("_cw_") or n == "_end":
            syms[n.lstrip("_")] = int(a, 16)
    dis = subprocess.run([os.path.join(SH, "sh-elf-objdump"), "-d", elf], capture_output=True, text=True).stdout
    # upstream build.sh's rule, on the mnemonic column only
    fpu = [l for l in dis.splitlines() if len(l.split("\t")) >= 3 and
           re.match(r"^(f[a-z.]+|frchg|fschg)\s|.*(fpscr|fpul)", l.split("\t")[2])]
    if fpu:
        raise SystemExit("cw.c compiled to FPU instructions: %s" % fpu[:3])
    return open(binf, "rb").read(), syms


def build():
    ro, rd = load_upstream()
    os.makedirs(OUT, exist_ok=True)
    cave = ro.cave_bytes()
    copy5 = rd.copy_bytes()
    assert ro.COPY5 == rd.COPY5
    assert ro.CAVE + len(cave) <= ro.MODE_ADDR, "cave code runs into the MODE byte"
    files = {"overview_cave.bin": (ro.CAVE, cave), "copy5.bin": (ro.COPY5, copy5)}
    hooks = [{"addr": hex(ro.HOOK_POOL), "size": 4, "stock": hex(ro.ORIG_RELEASE), "value": hex(ro.CAVE),
              "what": "overview: painter's release-call pool word -> cave"}]
    if os.path.exists(os.path.join(ROOT, "work", "sh-tools", "bin", "sh-elf-gcc")):
        cw, syms = cw_build_mk1(ro, rd)
        dcave = rd.assemble(rd._src(syms))
        dcave2 = rd.assemble(rd._src2(syms))
        assert rd.DCAVE + len(dcave) <= rd.DCAVE2 and rd.DCAVE2 + len(dcave2) <= rd.COPY5
        assert rd.CW_BASE + len(cw) <= syms["end"] <= ro.SNAP, "cw module overlaps the snapshot slots"
        files.update({"cw.bin": (rd.CW_BASE, cw), "dcave.bin": (rd.DCAVE, dcave), "dcave2.bin": (rd.DCAVE2, dcave2)})
        hooks += [
            {"addr": hex(rd.POOL), "size": 4, "stock": hex(rd.PALETTE), "value": hex(rd.DCAVE), "what": "centre: palette pool -> dcave"},
            {"addr": hex(rd.INSN), "size": 2, "stock": "0x4200", "value": hex(rd.INSN_NEW), "what": "centre: shll r2 -> jsr @r4"},
            {"addr": hex(rd.ROWINC[0]), "size": 2, "stock": hex(rd.ROWINC[1]), "value": hex(rd.ROWINC[2]), "what": "centre: row load -> post-increment"},
            {"addr": hex(rd.POOL2), "size": 4, "stock": hex(rd.PALETTE2), "value": hex(rd.DCAVE2), "what": "PERFORM strip: palette pool -> dcave2"},
            {"addr": hex(rd.INSN2), "size": 2, "stock": "0x4200", "value": hex(rd.INSN2_NEW), "what": "PERFORM strip: shll r2 -> jsr @r6"},
            {"addr": hex(rd.ROWINC2[0]), "size": 2, "stock": hex(rd.ROWINC2[1]), "value": hex(rd.ROWINC2[2]), "what": "PERFORM strip: row load -> post-increment"},
        ]
        zero = {"cw_bss": (rd.CW_BASE + len(cw), syms["end"] - rd.CW_BASE - len(cw)), "SLOT7_word": (rd.SLOT7, 4),
                "DSCRATCH": (rd.DSCRATCH & ~3, 4)}
    else:
        zero = {}
        print("rgb_mk1: no work/sh-tools/bin/sh-elf-gcc yet: overview only")
    # the cave's state words after its blob (MODE, THEME_FLAG, P5FLAG, SCRATCH, STEPVAR): upstream relied
    # on the 700's RAM being zero there; MK1's deck RAM is 0xff junk (deck survey 2026-11-01), and a
    # non-zero THEME_FLAG makes the painter jsr into THEME_CODE (junk)
    zero["cave_state"] = (ro.MODE_ADDR, ro.STEPVAR + 4 - ro.MODE_ADDR)
    for n, (a, b) in files.items():
        open(os.path.join(OUT, n), "wb").write(b)
    inst = {
        "model": MODEL["model"], "fw": MODEL["fw"], "home": hex(HOME),
        "order": "blobs first (VM stopped), then the hook pool word as ONE 32-bit store",
        "blobs": [{"file": n, "addr": hex(a), "len": len(b)} for n, (a, b) in files.items()],
        "hooks": hooks,
        "zero_first": {k: {"addr": hex(a), "len": n} for k, (a, n) in zero.items()},
        "mode_addr": hex(ro.MODE_ADDR), "modes": ro.MODES,
        "slots": {"SLOT4": hex(ro.SLOT4), "SLOT6": hex(ro.SLOT6), "SNAP_HASH": hex(ro.SNAP_HASH),
                  "SLOT5": hex(ro.SLOT5), "SLOT5_MAX": hex(ro.SLOT5_MAX)},
        "upstream_constants_replaced": ["HOOK_POOL", "ORIG_RELEASE", "CTX_TAB", "IDX_OFF", "PREVIEW",
                                         "CAVE (env)", "SNAP (env)"],
    }
    json.dump(inst, open(os.path.join(OUT, "install.json"), "w"), indent=1)
    print(json.dumps(inst, indent=1))
    return inst


def install_script(mode, centre=True):
    """emu.py script steps that install the build (same order a deck installer
    would use): blobs, zeroed areas, the mode byte, then every hook as one store."""
    j = json.load(open(os.path.join(OUT, "install.json")))
    steps = ["load %s %s" % (b["addr"], os.path.join(OUT, b["file"])) for b in j["blobs"]
             if centre or b["file"] in ("overview_cave.bin", "copy5.bin")]
    steps += ["fill %s %#x 0" % (z["addr"], z["len"]) for k, z in j["zero_first"].items()
              if centre or k == "cave_state"]
    steps.append("fill %s 1 %d" % (j["mode_addr"], mode))
    for h in j["hooks"]:
        if not centre and not h["what"].startswith("overview"):
            continue
        steps.append("poke%d %s %s" % (8 * h["size"], h["addr"], h["value"]))
    return "; ".join(steps)


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        build()
    elif sys.argv[1:2] == ["script"]:
        print(install_script(int(sys.argv[2])))
    else:
        print(__doc__)
