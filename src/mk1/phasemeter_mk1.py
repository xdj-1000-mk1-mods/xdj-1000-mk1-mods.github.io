#!/usr/bin/env python3
"""Phase meter (Type 1) for MK1 v1.13, built from upstream's own code.

Upstream tools/phasemeter/pm.c + pmhook.S (+ the shipped pm_label.h),
compiled with ONLY their model-specific constants replaced from
mk1/models/xdj1000_113.json (each must match exactly once, else the build
stops). The geometry is the same on MK1 (model table phasemeter_geometry);
the build asserts upstream still uses those numbers.
MSOFF (MY SETTINGS 'MODS OFF', not on MK1) and TS_DATA (theme switcher,
not on MK1; only read when pm_light != 0) point at zero words at the end
of the module area that the installer clears.

Install (as upstream phasemeter_apply.py): module, zero its state,
pm_prev = live flush-hook value (chains whatever is there), pm_mode = 1,
then the hook as ONE store. Revert: hook back to pm_prev.

    phasemeter_mk1.py build   -> work/pm/build/pm.bin + pm.syms
    phasemeter_mk1.py emu     qemu test from state 'perform' (paused):
                              ticks checked against pm.c's own formula on
                              PERFORM and main, BROWSE untouched
"""
import json
import os
import re
import shutil
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import shbuild                                                 # noqa: E402

E_ = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
MOD, GEO = E_["phasemeter_module"], E_["phasemeter_geometry"]
BASE, END_MAX = int(MOD["addr"], 16), int(MOD["end_max"], 16)
FLAGS = END_MAX - 16                       # zero words: MSOFF byte, TS_DATA word
HOOK, HOOK_STOCK = int(E_["flush_hook"]["slot"], 16), int(E_["flush_hook"]["stock"], 16)
MODEW = int(E_["screen_mode_word"]["addr"], 16)
POSL = int(E_["play_position"]["addr"], 16)
UP = os.path.join(ROOT, "tools", "phasemeter")
OUT = os.path.join(ROOT, "work", "pm", "build")


def _set(src, name, value):
    pat = r"(#define %s\s+)0x[0-9A-Fa-f]+u" % name
    if len(re.findall(pat, src)) != 1:
        raise SystemExit("phasemeter_mk1: expected exactly one '#define %s' in upstream pm.c" % name)
    return re.sub(pat, lambda m: m.group(1) + "0x%08Xu" % value, src)


def _has(src, text):
    if src.count(text) != 1:
        raise SystemExit("phasemeter_mk1: upstream pm.c no longer has %r (geometry changed?)" % text)


MASTER_FN = r"""
/* MK1 port addition: the orange (master) row. Upstream left it a dim line.
 * The firmware's own tempo-master player number (LM_NUM) picks the player:
 * status slot LM_TAB + n*LM_STRIDE + LM_STAT_OFF (flags +9 bit 0x20 = master,
 * BPM*100 u16 +0x10, pitch u32 +0x0c, 0x100000 = 0%%), beat-in-bar byte
 * LM_BIB + n, which changes ON the beat (beat packets); the sub-beat fraction
 * is the time since that change (kernel ms clock) over the beat length.
 * If this deck is master (its own slot carries no master flag): mirror its
 * own beats. Addresses: mk1/models/xdj1000_113.json link_master, ms_clock. */
#define LM_NUM      0x%08Xu
#define LM_TAB      0x%08Xu
#define LM_STRIDE   0x%Xu
#define LM_STAT_OFF 0x%Xu
#define LM_BIB      0x%08Xu
#define LM_MAXN     %du
#define MS_CLK      0x%08Xu
static u8 lm_last;
u32 pm_lm_n, pm_lm_hits;                            /* test probes: player followed, beats used */
static u32 lm_t;

static int master_beat(int *frac, int *bib)
{
    u32 n = R8(LM_NUM);
    if (n < 1 || n > LM_MAXN) return 0;
    u32 st = LM_TAB + n * LM_STRIDE + LM_STAT_OFF;
    u8 b = R8(LM_BIB + n);
    u32 now = R32(MS_CLK);
    if (n != pm_lm_n) { pm_lm_n = n; lm_last = 0; }
    if (b != lm_last) { lm_last = b; lm_t = now; }
    if (b < 1 || b > 4 || !(R8(st + 9) & 0x20)) return 0;
    u32 bpm = R16(st + 0x10), pitch = R32(st + 0x0C);
    u32 eff = (bpm * (pitch >> 8)) >> 12;           /* BPM*100 at the pitch */
    if (eff < 2000 || eff > 40000) return 0;
    u32 beat_ms = 6000000u / eff, dt = now - lm_t;
    if (dt > beat_ms) dt = beat_ms;                 /* late packet: wait on the beat */
    *frac = (int)((dt << 8) / beat_ms);
    *bib = b;
    pm_lm_hits++;
    return 1;
}

static void master_ticks(u16 *lay, int stride, int frac, int bib, u16 tick)
{
    for (int x = X0; x <= X1; x++) { put(lay, stride, x, OY, C_OR); put(lay, stride, x, OY + 1, C_OR); }
    for (int k = -5; k <= 5; k++) {
        int x = CX + (((k << 8) - frac) * (X1 - X0)) / (8 << 8);
        if ((((bib - 1 + k) %% 4) + 4) %% 4 == 0) {   /* downbeat */
            vline(lay, stride, x - 1, OY - 8, OY + 9, C_RED);
            vline(lay, stride, x, OY - 8, OY + 9, C_RED);
        } else {
            vline(lay, stride, x, OY - 8, OY - 2, tick);
        }
    }
}

void pm_draw(u16 *lay, int stride)"""

MASTER_DRAW = """    {   /* MK1: master row (linked master, else this deck's own beats) */
        int mf = 0, mb = 0;
        if (master_beat(&mf, &mb))
            master_ticks(lay, stride, mf, mb, tick);
        else if (i >= 0)
            master_ticks(lay, stride, frac, pm_bar[i] + 0, tick);
    }
    for (int y = TOPY - 1; y <= BOTY + 1; y++)       /* now */"""


GRID_FN = r"""static int snapshot_grid(void)
{
    /* MK1: the deck's own grid table (models deck_grid), filled for USB and
     * LINK loads alike; the USB slot's ANLZ ctx (below) has no grid for a
     * track loaded over LINK. 0 = retry next frame (table not filled yet). */
    pm_n = 0;
    if (R32(DG_VALID) == 1u) {
        u32 n = R32(DG_COUNT);
        if (n >= 2 && n <= DG_MAX) {
            if (n > MAXBEATS) n = MAXBEATS;
            const volatile u32 *e = (const volatile u32 *)DG_ENTRIES;
            u32 prev = 0;
            for (u32 i = 0; i < n; i++, e += 2) {
                u32 ms = e[0], b = e[1];
                if (b < 1 || b > 4 || (i && ms <= prev)) {
                    pm_rejects++;
                    return 0;
                }
                pm_bar[i] = (u8)b;
                pm_ms[i] = prev = ms;
            }
            if (R32(DG_VALID) != 1u || R32(DG_COUNT) < n) {
                pm_rejects++;
                return 0;
            }
            pm_n = n;
            pm_src = 1;
            return 1;
        }
    }
    pm_src = 2;
    return snapshot_ctx();
}
"""


DG_SIG = r"""
/* MK1: the snapshot key includes the deck grid table, so a grid that arrives
 * after the track's preview (LINK loads on the deck: the grid comes over the
 * network later) is taken when it lands, and a table still holding the last
 * track's grid is retaken when it is replaced. */
static u32 dg_sig(void)
{
    const volatile u32 *e = (const volatile u32 *)DG_ENTRIES;
    return (R32(DG_VALID) * 0x9E3779B1u) ^ (R32(DG_COUNT) * 0x85EBCA77u) ^ (e[0] * 0xC2B2AE3Du) ^ e[1];
}
"""


def deck_grid(c):
    g = E_["deck_grid"]
    for t in ("static int snapshot_grid(void)\n{", "    pm_n = n;\n    return 1;\n}\n"):
        _has(c, t)
    c = c.replace("static int snapshot_grid(void)\n{", "static int snapshot_ctx(void)\n{", 1)
    i = c.index("    pm_n = n;\n    return 1;\n}\n", c.index("static int snapshot_ctx(void)")) + len("    pm_n = n;\n    return 1;\n}\n")
    defs = ("#define DG_VALID   0x%08Xu\n#define DG_COUNT   0x%08Xu\n#define DG_ENTRIES 0x%08Xu\n#define DG_MAX     %du\n"
            "u32 pm_src;                                         /* 1 deck table, 2 ANLZ ctx */\n"
            % (int(g["valid"], 16), int(g["count"], 16), int(g["entries"], 16), g["max_count"]))
    c = c[:i] + "\n" + defs + GRID_FN + DG_SIG + c[i:]
    _has(c, "    u32 h = hash_preview();\n")
    return c.replace("    u32 h = hash_preview();\n", "    u32 h = hash_preview() ^ dg_sig();\n", 1)


def master_row(c):
    lm, ck = E_["link_master"], E_["ms_clock"]
    for t in ("void pm_draw(u16 *lay, int stride)",
              "    for (int y = TOPY - 1; y <= BOTY + 1; y++)       /* now */"):
        _has(c, t)
    c = c.replace("void pm_draw(u16 *lay, int stride)",
                  MASTER_FN % (int(lm["master_number"], 16), int(lm["slot_table"], 16), int(lm["slot_stride"], 16),
                               int(lm["slot_status_off"], 16), int(lm["beat_in_bar_base"], 16), lm["max_player"],
                               int(ck["addr"], 16)))
    return c.replace("    for (int y = TOPY - 1; y <= BOTY + 1; y++)       /* now */", MASTER_DRAW)


def build():
    src = os.path.join(OUT, "src")
    os.makedirs(src, exist_ok=True)
    c = open(os.path.join(UP, "pm.c")).read()
    h = lambda v: int(v, 16)
    for name, v in (("MODEW", MODEW), ("CTX_TAB", h(E_["anlz_ctx_table"]["addr"])),
                    ("PQTZ_OFF", h(E_["beat_grid"]["ctx_off"])), ("TAG_PQTZ", h(E_["beat_grid"]["tag"])),
                    ("POSL", POSL), ("PREVIEW", h(E_["preview_word"]["addr"]))):
        c = _set(c, name, v)
    for t in ("#define X0 %d" % GEO["x0"], "#define X1 %d" % GEO["x1"], "#define CX %d" % GEO["cx"],
              "#define PERFORM_DY (%d)" % GEO["perform_dy"], "#define TOPY (%d + pm_dy)" % GEO["main_rows_y"][0],
              "#define BOTY (%d + pm_dy)" % GEO["main_rows_y"][1]):
        _has(c, t)
    lab = open(os.path.join(UP, "pm_label.h")).read()
    for k, v in zip(("LABEL_X", "LABEL_Y", "LABEL_W", "LABEL_H"), GEO["label"]):
        if "#define %s %d\n" % (k, v) not in lab:
            raise SystemExit("phasemeter_mk1: pm_label.h %s != %d" % (k, v))
    c = master_row(c)
    c = deck_grid(c)
    open(os.path.join(src, "pm.c"), "w").write(c)
    shutil.copy(os.path.join(UP, "pm_label.h"), os.path.join(src, "pm_label.h"))
    s = open(os.path.join(UP, "pmhook.S")).read()
    if s.count("_pm_prev: .long 0x08E7D278") != 1:
        raise SystemExit("phasemeter_mk1: pmhook.S changed upstream")
    open(os.path.join(src, "pmhook.S"), "w").write(s.replace("_pm_prev: .long 0x08E7D278",
                                                           "_pm_prev: .long 0x%08X" % HOOK_STOCK))
    img, syms = shbuild.build(OUT, "pm", ["pmhook.S", "pm.c"], BASE, FLAGS,
                              {"MSOFF": FLAGS, "TS_DATA": FLAGS + 4}, "_pm_entry",
                              keep=("_pm_", "_end"), text_off=0x40, cwd=src)
    assert syms["pm_entry"] == BASE, syms
    return img, syms


def install_steps(s, live_hook):
    blob = os.path.join(OUT, "pm_installed.bin")
    img = bytearray(open(os.path.join(OUT, "pm.bin"), "rb").read())
    struct.pack_into("<I", img, s["pm_prev"] - BASE, live_hook)
    open(blob, "wb").write(img)
    n = len(img)
    return ["fill %#x %#x 0" % (BASE + n, END_MAX - BASE - n),          # state + the zero flags
            "load %#x %s" % (BASE, blob),
            "fill %#x 1 1" % s["pm_mode"],
            "poke32 %#x %#x" % (HOOK, BASE)]


def expected(posl, grid, dy):
    """pm.c's tick positions for a position: [(x, downbeat)]"""
    ms = posl * 20 // 3
    t = [m for _, _, m in grid]
    if ms < t[0]:
        return []
    lo = max(i for i in range(len(t)) if t[i] <= ms)
    if lo == len(t) - 1:
        frac = 0
    else:
        frac = ((ms - t[lo]) << 8) // (t[lo + 1] - t[lo])
    out = []
    for k in range(-5, 6):
        j = lo + k
        if 0 <= j < len(t):
            num = ((k << 8) - frac) * (GEO["x1"] - GEO["x0"])
            x = GEO["cx"] + int(num / (8 << 8))            # C division truncates toward 0
            if GEO["x0"] <= x <= GEO["x1"]:
                out.append((x, grid[j][0] == 1))
    return out


def grid(E, model):
    u32 = lambda a: struct.unpack("<I", E.peek(model, a, 4))[0]
    ctx = u32(int(E_["anlz_ctx_table"]["addr"], 16))
    q = ctx + int(E_["beat_grid"]["ctx_off"], 16)
    n, ep = u32(q + 0x14), u32(q + 0x18)
    g = E.peek(model, ep, 8 * n)
    return [struct.unpack_from("<HHI", g, 8 * i) for i in range(n)]


def meter_ok(E, model, G, shot, dy):
    """deck PAUSED: every tick/downbeat where pm.c puts it for the current
    position, the now line and the blue row drawn, the stock boxes gone"""
    from PIL import Image
    u32 = lambda a: struct.unpack("<I", E.peek(model, a, 4))[0]
    posl = u32(POSL)
    E.shot(model, shot)
    time.sleep(0.3)
    assert u32(POSL) == posl, "position moved while paused"
    px = Image.open(shot).convert("RGB").load()
    by = 150 + dy
    cx = GEO["cx"]
    ex = [(x, d) for x, d in expected(posl, G, dy) if abs(x - cx) > 1]   # pm.c draws the now line over them
    red = lambda c: c[0] > 180 and c[1] < 90 and c[2] < 90
    grey = lambda c: abs(c[0] - 150) < 30 and abs(c[1] - 150) < 30 and abs(c[2] - 150) < 30
    good = sum((red(px[x, by - 6]) and red(px[x, by + 6])) if down else grey(px[x, by - 5]) for x, down in ex)
    now = all(sum(px[x, y]) > 700 for x in (365, 366, 367) for y in (115 + dy, 140 + dy, 159 + dy))
    blue = sum(1 for x in range(262, 470) if px[x, by][2] > 180 and px[x, by][0] < 80) > 150
    stock_gone = px[260, 120 + dy] != (136, 60, 0)              # stock box border 0x89E0
    print("  %s: POSL %d (%.2f s), %d ticks expected, %d where pm.c puts them; now line %s, blue row %s" % (
        os.path.basename(shot), posl, posl / 150, len(ex), good, now, blue), flush=True)
    return len(ex) >= 6 and good == len(ex) and now and blue and stock_gone


def meter_gone(shot, dy):
    """pm_mode 0: no white now line through the meter rows, label area empty"""
    from PIL import Image
    px = Image.open(shot).convert("RGB").load()
    now = all(sum(px[366, y]) > 700 for y in (115 + dy, 140 + dy))
    label = sum(1 for x in range(172, 258) for y in range(116 + dy, 146 + dy) if sum(px[x, y]) > 60)
    return not now and label == 0


def emu():
    import emu as E
    from PIL import Image
    model = "xdj1000"
    shots = os.path.join(ROOT, "work", "pm", "shots")
    os.makedirs(shots, exist_ok=True)
    img, s = build()
    p = E.start(model, incoming=os.path.join(E.WORK, model, "perform.vm"))
    ok = True

    def chk(label, good):
        print(("ok   " if good else "FAIL ") + label, flush=True)
        return bool(good)

    def u32(a):
        return struct.unpack("<I", E.peek(model, a, 4))[0]

    try:
        for _ in range(240):
            if "running" in E.cmd(model, "info status"):
                break
            time.sleep(0.25)
        time.sleep(2)
        E.step(model, "key 0x10:0x01:300")                       # pause
        time.sleep(1.5)
        live = u32(HOOK)
        ok &= chk("stock: hook %#x, PERFORM (mode %d)" % (live, u32(MODEW)), live == HOOK_STOCK and u32(MODEW) == 7)
        ok &= chk("module area empty", E.peek(model, BASE, END_MAX - BASE) == bytes(END_MAX - BASE))
        G = grid(E, model)
        E.shot(model, os.path.join(shots, "a_stock_perform.png"))
        for st in install_steps(s, live):
            E.step(model, st)
        time.sleep(2)
        ok &= chk("drawing (pm_draws %d), grid snapshot %d beats (deck %d)" % (u32(s["pm_draws"]), u32(s["pm_n"]), len(G)),
                  u32(s["pm_draws"]) > 10 and u32(s["pm_n"]) == len(G))
        ok &= chk("PERFORM meter matches pm.c", meter_ok(E, model, G, os.path.join(shots, "b_perform.png"), -103))
        E.step(model, "key 0x10:0x01:300")                       # play 3 s, pause: scrolled
        time.sleep(3)
        E.step(model, "key 0x10:0x01:300")
        time.sleep(1.5)
        ok &= chk("PERFORM after 3 s of play", meter_ok(E, model, G, os.path.join(shots, "c_perform_later.png"), -103))
        E.step(model, "tap 711 37 300")                          # PERFORM off -> main
        time.sleep(2)
        ok &= chk("main screen (mode %d)" % u32(MODEW), u32(MODEW) == 1)
        ok &= chk("main meter matches pm.c", meter_ok(E, model, G, os.path.join(shots, "d_main.png"), 0))
        d0 = u32(s["pm_draws"])
        E.step(model, "tap 164 37 300")                          # BROWSE
        time.sleep(2)
        E.shot(model, os.path.join(shots, "e_browse.png"))
        time.sleep(1)
        d1 = u32(s["pm_draws"])
        time.sleep(1)
        ok &= chk("BROWSE (mode %d): no drawing (%d -> %d)" % (u32(MODEW), d1, u32(s["pm_draws"])),
                  u32(MODEW) != 1 and u32(MODEW) != 7 and u32(s["pm_draws"]) == d1)
        E.step(model, "tap 164 37 300")                          # back
        time.sleep(2)
        ok &= chk("back on main: drawing again", u32(s["pm_draws"]) > d1 or u32(MODEW) not in (1, 7))
        print("diag: rejects %d visfail %d stripped %d fills %d lines %d" % (
            u32(s["pm_rejects"]), u32(s["pm_visfail"]), u32(s["pm_stripped"]), u32(s["pm_nfill"]), u32(s["pm_nline"])))
        ok &= chk("deck running", "running" in E.cmd(model, "info status"))
    finally:
        try:
            E.cmd(model, "quit")
        except OSError:
            pass
        p.wait(timeout=60)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        build()
    elif sys.argv[1:] == ["emu"]:
        sys.exit(emu())
    else:
        print(__doc__)
