#!/usr/bin/env python3
"""All finished RAM mods on one stick (XDJ-1000 MK1, loader firmware 1.13-MOD).

    mods_all.py build [--mode rgb|3band|blue]   -> work/mods_all/MODS.BIN + MODS2.BIN
    mods_all.py emu                              qemu: flashed loader image, stick with both files

MODS.BIN  (read by the flashed loader, 60 KB stage) = bootstrap only: loader2
          (ldr.c again: MODS2.BIN, 512 KB stage at 0x09a00000) + the mount
          check's path_build pool word: loader1 entry -> loader2 entry. The
          mount check reloads that word for exportExt.pdb right after
          export.pdb, so loader2 runs in the same mount.
MODS2.BIN = every finished mod, one CHECK (no track loaded), all blocks, then
          one STORE per hook word (first stock -> final chain head):
  rgb + UTILITY rows + phase meter (snapshot 2026-11-02), 3-BAND from .2EX
  (ext2_mk1), BEAT JUMP swipe (bjswipe_mk1), stems mixer (stems_mk1) + STEMS
  control (stemsui_mk1). Chains: flush slot -> STEMS UI -> phase meter -> stock;
  touch slot -> STEMS UI -> beat-jump swipe -> stock.
Not included: live key shift + KEY SHIFT control (its installer needs a runtime
result before the last write, and upstream's 'freeze + file corrupted' report
is open).
"""
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import loader_mk1 as LD                                         # noqa: E402
import shbuild                                                  # noqa: E402

M = LD.M
H = LD.H
L2 = M["loader2"]
BASE2, END2, STATE2 = H(L2["addr"]), H(L2["end_max"]), H(L2["state"])
STAGE2, STAGE2_END = H(L2["stage"]), H(L2["stage_end"])
FREE2 = (0x09800000, 0x09A80000)                                # ram_home_candidate + ram_free_2 (deck surveys)
OUT = os.path.join(ROOT, "work", "mods_all")
MODES = {"blue": 0, "rgb": 1, "3band": 2}


def cfg_defs(name=False):
    """stick settings (models stick_settings): state, the two live setting words"""
    c = M["stick_settings"]
    B = json.load(open(os.path.join(LD.SNAP, "bundle.json")))
    d = dict(CFG_STATE=H(c["state"]), CFG_WAVE=H(c["wave_word"]), CFG_PM=H(B["phasemeter"]["pm_mode"]))
    assert H(B["rgb"]["mode"][0]) == d["CFG_WAVE"]
    if name:
        d["CFG_NAME"] = '"%s"' % c["file"]
    return d


def build_loader2():
    d = dict(PB_STOCK=LD.POOL_STOCK, OPEN_R=H(LD.L["open_r"]), READ_DB=H(LD.L["read_db"]),
             CLOSE_DB=H(LD.L["close_db"]), NAME_PDB=0xA8079588,           # 'PIONEER/rekordbox/exportExt.pdb' (stick_mount_check)
             STATE=STATE2, STAGE=STAGE2, STAGE_END=STAGE2_END,
             FREE_LO=FREE2[0], FREE_HI=FREE2[1], LDR_LO=BASE2, FILE_NAME='"MODS2.BIN"',
             DRIVE_WORD=H(M["ext2_module"]["drive_word"]), **cfg_defs(name=True))
    src = os.path.join(HERE, "loader")
    img, syms = shbuild.build(OUT, "ldr2", [os.path.join(src, "ldrentry.S"), os.path.join(src, "ldr.c")],
                              BASE2, END2, d, "_ldr_head", keep=("_ldr_", "_end"),
                              extra=("-fno-tree-loop-distribute-patterns",))
    assert syms["ldr_head"] == BASE2 and syms["end"] <= END2, syms
    return img, syms


LX = M["stick_loader_x"]
BASEX, ENDX, STATEX = H(LX["addr"]), H(LX["end_max"]), H(LX["state"])
STAGEX, STAGEX_END = H(LX["stage"]), H(LX["stage_end"])
LINK_POOL, LINK_STOCK = H(M["link_drive"]["link_pool"]), H(M["link_drive"]["set_drive_type"])


def build_loaderx():
    """loader X = the enabler v2's loader (ldr.c with LINK_SET_STOCK): MODSX.BIN from
    the deck's own stick (mount check) or from the linked player's stick (link mount)"""
    FA = M["file_api"]
    d = dict(PB_STOCK=LD.POOL_STOCK, OPEN_R=H(LD.L["open_r"]), READ_DB=H(LD.L["read_db"]),
             CLOSE_DB=H(LD.L["close_db"]), NAME_PDB=H(LD.L["name_pdb"]),
             STATE=STATEX, STAGE=STAGEX, STAGE_END=STAGEX_END, FREE_LO=FREE2[0], FREE_HI=FREE2[1], LDR_LO=BASEX,
             FILE_NAME='"%s"' % LX["file"], LINK_SET_STOCK=LINK_STOCK,
             FOPEN_W=H(FA["fopen_w"]), FREAD_C=H(FA["fread_c"]), FCLOSE_C=H(FA["fclose_c"]))
    src = os.path.join(HERE, "loader")
    out = os.path.join(ROOT, "work", "loaderx")
    os.makedirs(out, exist_ok=True)
    img, syms = shbuild.build(out, "ldrx", [os.path.join(src, "ldrentry.S"), os.path.join(src, "ldr.c")],
                              BASEX, ENDX, d, "_ldr_head", keep=("_ldr_", "_end"), text_off=0x20,
                              extra=("-fno-tree-loop-distribute-patterns",))
    assert syms["ldr_head"] == BASEX and struct.unpack_from("<I", img, 4)[0] == syms["ldr_path_build"]
    assert struct.unpack_from("<I", img, 16)[0] == syms["ldr_link_mount"] and struct.unpack_from("<I", img, 12)[0] == 2
    return img, syms


def bake_x(dec, log=print):
    """flash form of loader X: as loader_mk1.bake, plus the LINK set-drive-type pool word"""
    import permanent_mk1 as PM
    img, s = build_loaderx()
    m = PM.Img(dec)
    assert m.r32(LD.POOL) == LD.POOL_STOCK, "path_build pool not stock in the image"
    assert m.r32(LINK_POOL) == LINK_STOCK, "link set-drive-type pool not stock in the image"
    m.zero_fill(STATEX, 0x100)
    m.write(BASEX, img)
    m.write(LD.POOL, struct.pack("<I", s["ldr_path_build"]))
    m.write(LINK_POOL, struct.pack("<I", s["ldr_link_mount"]))
    tail, jobs, n = PM.boot_tail(m)
    log("loader X: module %#x (+%d B), state %#x zeroed, mount pool %#x -> %#x, link pool %#x -> %#x; "
        "boot copier %d jobs at %#x (+%d B)" % (BASEX, len(img), STATEX, LD.POOL, s["ldr_path_build"],
                                                 LINK_POOL, s["ldr_link_mount"], len(jobs), tail, n))
    return s


def plan_x(mode="rgb", stems=True):
    """MODSX.BIN: everything in one file. The mods (plan2), then loader2 as the stick-side
    service (drive word + MODSCFG.BIN on every own-stick mount), its state preset to
    'installed OK' so it never looks for MODS2.BIN, and the mount pool: loader X -> loader2."""
    lx_img, lx = build_loaderx()
    l2img, l2 = build_loader2()
    ops, info = plan2(mode, stems)
    st = struct.pack("<3I", 0x5453444C, 0x454E4F44, 2) + bytes(0x100 - 12)      # 'LDST', 'DONE', S_OK
    ops = ops + [(LD.OP_COPY, BASE2, l2img, 0), (LD.OP_COPY, STATE2, st, 0),
                 (LD.OP_STORE, LD.POOL, lx["ldr_path_build"], l2["ldr_path_build"], 0)]
    return ops, info, lx, l2


def cmd_build_x(mode="rgb", stems=None):
    if stems is None:
        stems = os.environ.get("XDJMOD_STEMS", "1") != "0"
    os.makedirs(OUT, exist_ok=True)
    ops, info, lx, l2 = plan_x(mode, stems)
    blob = LD.pack(ops, cap=STAGEX_END - STAGEX)
    open(os.path.join(OUT, LX["file"]), "wb").write(blob)
    print("%-10s %7d B  sha256 %s" % (LX["file"], len(blob), hashlib.sha256(blob).hexdigest()))
    print("loader X entries: mount %#x, link %#x; %d ops (%d STORE); overlapping blocks: %s"
          % (lx["ldr_path_build"], lx["ldr_link_mount"], len(ops), sum(o[0] == LD.OP_STORE for o in ops),
             overlaps(ops) or "none"))
    return blob, ops, info, lx, l2


def bootstrap(l2img, l2syms):
    l1img, l1 = LD.build()                                     # = the flashed loader (sha checked by the caller)
    return [(LD.OP_COPY, BASE2, l2img, 0),
            (LD.OP_ZERO, STATE2, 0x100, 0),
            (LD.OP_STORE, LD.POOL, l1["ldr_path_build"], l2syms["ldr_path_build"], 0)]


class Steps:
    """emu.py install steps (fill / load / poke32) -> loader ops"""
    def __init__(self):
        self.blocks, self.stores = [], []

    def add(self, steps, stock):
        for st in steps:
            a = st.split()
            if a[0] == "fill":
                addr, n = int(a[1], 0), int(a[2], 0)
                assert int(a[3], 0) == 0
                lo, hi = (addr + 3) & ~3, (addr + n + 3) & ~3          # the COPY before pads to 4 with zeros
                if hi > lo:
                    self.blocks.append((LD.OP_ZERO, lo, hi - lo, 0))
            elif a[0] == "load":
                self.blocks.append((LD.OP_COPY, int(a[1], 0), open(a[2], "rb").read(), 0))
            elif a[0] == "poke32":
                addr, v = int(a[1], 0), int(a[2], 0)
                if FREE2[0] <= addr < FREE2[1]:
                    self.blocks.append((LD.OP_COPY, addr, struct.pack("<I", v), 0))
                else:
                    self.stores.append((addr, stock[addr], v))
            else:
                raise SystemExit("mods_all: step %r not convertible" % st)


def plan2(mode="rgb", stems=True):
    import bjswipe_mk1 as BJ
    import ext2_mk1 as X2
    import stems_mk1 as SM
    import stemsui_mk1 as SU
    import phasemeter_mk1 as PM
    base = LD.plan(mode=MODES[mode])                           # rgb + UTILITY + phase meter (snapshot)
    check = [o for o in base if o[0] == LD.OP_CHECK]
    blocks = [o for o in base if o[0] not in (LD.OP_CHECK, LD.OP_STORE)]
    stores = [(o[1], o[2], o[3], o[4]) for o in base if o[0] == LD.OP_STORE]
    xb, xs, xsyms = X2.ops(LD.OP_COPY, LD.OP_ZERO, LD.OP_STORE, settings=cfg_defs())
    blocks += xb
    stores += [(o[1], o[2], o[3], o[4]) for o in xs]
    import lnk_mk1 as LK                                       # colour / 3-band for LINK loads
    lb, ls, lsyms = LK.ops(LD.OP_COPY, LD.OP_ZERO, LD.OP_STORE)
    blocks += lb
    stores += [(o[1], o[2], o[3], o[4]) for o in ls]
    S = Steps()
    bimg, bs = BJ.build()
    S.add(BJ.install_steps(bs), {BJ.SLOT: BJ.STOCK})
    ss = us = None
    if stems:                                                  # stems mixer + STEMS UI (needs a PERFORM screenshot)
        simg, ss = SM.build()
        S.add(SM.install_steps(ss, SM.HOOK_STOCK), {SM.HOOK: SM.HOOK_STOCK, SM.DIRECT: SM.HOOK_STOCK})
        uimg, us = SU.build()
        pm_base = PM.BASE
        S.add(SU.install_steps(us, pm_base, bs["bj_entry"]), {SU.FLUSH: pm_base, SU.TOUCH: bs["bj_entry"]})
    blocks += S.blocks
    stores += [(a, st, nw, 0) for a, st, nw in S.stores]
    # one STORE per word: first stock -> last value (chains are preset in the module blocks)
    final, order = {}, []
    for a, st, nw, fl in stores:
        if a in final:
            assert final[a][1] == st, "chain break at %#x: %#x then stock %#x" % (a, final[a][1], st)
            final[a] = (final[a][0], nw, final[a][2])
        else:
            final[a] = (st, nw, fl)
            order.append(a)
    st_ops = [(LD.OP_STORE, a, final[a][0], final[a][1], final[a][2]) for a in order]
    ops = check + blocks + st_ops
    info = dict(bj=bs, stems=ss, stemsui=us, ext2=xsyms, lnk=lsyms)
    return ops, info


def overlaps(ops):
    """COPY/ZERO ranges that overlap across different modules (ZERO+COPY of one module's own bss is fine)"""
    rs = []
    for o in ops:
        if o[0] == LD.OP_COPY:
            rs.append((o[1], o[1] + ((len(o[2]) + 3) & ~3)))
        elif o[0] == LD.OP_ZERO:
            rs.append((o[1], o[1] + o[2]))
        elif o[0] == LD.OP_MEMCPY:
            rs.append((o[1], o[1] + o[3]))
    rs.sort()
    bad = []
    for (a0, e0), (a1, e1) in zip(rs, rs[1:]):
        if a1 < e0:
            bad.append((hex(a0), hex(e0), hex(a1), hex(e1)))
    return bad


def cmd_build(mode="rgb", stems=None):
    if stems is None:
        stems = os.environ.get("XDJMOD_STEMS", "1") != "0"
    os.makedirs(OUT, exist_ok=True)
    l1img, _ = LD.build()
    assert hashlib.sha256(l1img).hexdigest().startswith("0752ff81"), "loader1 build != the flashed loader"
    l2img, l2 = build_loader2()
    boot = LD.pack(bootstrap(l2img, l2))
    ops, info = plan2(mode, stems)
    mods2 = LD.pack(ops, cap=STAGE2_END - STAGE2)
    assert len(mods2) <= STAGE2_END - STAGE2, "MODS2.BIN %d B > stage" % len(mods2)
    ov = overlaps(ops)
    for n, b in (("MODS.BIN", boot), ("MODS2.BIN", mods2)):
        open(os.path.join(OUT, n), "wb").write(b)
        print("%-10s %7d B  sha256 %s" % (n, len(b), hashlib.sha256(b).hexdigest()))
    print("loader2 %d B entry %#x state %#x; MODS2: %d ops (%d STORE), mode %s; overlapping blocks: %s"
          % (len(l2img), l2["ldr_path_build"], STATE2, len(ops), sum(o[0] == LD.OP_STORE for o in ops), mode,
             ov or "none"))
    for o in ops:
        if o[0] == LD.OP_STORE:
            print("   STORE %#010x  %#010x -> %#010x" % (o[1], o[2], o[3]))
    return boot, mods2, ops, info, l2

def emu(kernel=None, junk=True, link=False):
    """cold boot of the flashed loader image (deck-like junk in both free areas), stick =
    plain rekordbox export (3-band only in .2EX) + MODS.BIN + MODS2.BIN.
    link: on an emulated Pro DJ Link segment with software players 2/3/4
    (link_slots_emu.py); the phase meter's master row must follow the master."""
    import time
    if link:
        import link_slots_emu as LS                          # sets DJLINK, multicast on loopback
    import emu as E
    model = "xdj1000"
    kernel = kernel or os.path.join(ROOT, "work", "mk1build", "MAIN_mk1_113_version_tag_loader.img")
    boot, mods2, ops, info, l2 = cmd_build()
    src = os.path.join(OUT, "stick")
    import shutil
    import subprocess
    shutil.rmtree(src, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "work", "testusb", "device"), src)
    open(os.path.join(src, "MODS.BIN"), "wb").write(boot)
    open(os.path.join(src, "MODS2.BIN"), "wb").write(mods2)
    stick = os.path.join(OUT, "stick.img")
    subprocess.run([os.path.join(LD.NXS2, ".venv", "bin", "python"),
                    os.path.join(LD.NXS2, "scripts", "media", "make_usb_image.py"), src, stick, "64"],
                   check=True, cwd=LD.NXS2, stdout=subprocess.DEVNULL)
    shots = os.path.join(OUT, "shots")
    os.makedirs(shots, exist_ok=True)
    ok = True

    def chk(label, good):
        nonlocal ok
        print(("  ok   " if good else "  FAIL ") + label, flush=True)
        ok &= bool(good)

    u32 = lambda a: struct.unpack("<I", E.peek(model, a, 4))[0]
    procs = LS.start_players(LS.group_now(), master=3) if link else []
    p = E.start(model, stick=stick, paused=True, kernel=kernel)
    try:
        if junk and not os.path.exists(os.path.join(ROOT, "work", "survey", "ram_09800000.bin")):
            print("  (no deck RAM survey in work/survey/: free RAM starts zeroed)", flush=True)
            junk = False
        if junk:
            g = E.Gdb(model)
            for a, f in ((0x09800000, "ram_09800000.bin"), (0x09A00000, "ram_09a00000.bin")):
                jb = open(os.path.join(ROOT, "work", "survey", f), "rb").read()
                for o in range(0, len(jb), 0x200):
                    g.wr(a + o, jb[o:o + 0x200])
            g.detach()
            print("  junk RAM pre-filled (deck surveys)", flush=True)
        E.cmd(model, "cont")
        t0 = time.time()
        while time.time() - t0 < 180:
            time.sleep(3)
            try:
                if u32(STATE2) == 0x5453444C and u32(STATE2 + 8) not in (0, 1):
                    break
            except Exception:
                pass
        s1 = struct.unpack("<11I", E.peek(model, LD.STATE, 44))
        s2 = struct.unpack("<11I", E.peek(model, STATE2, 44))
        nm = lambda v: LD.STATUS[v] if v < len(LD.STATUS) else hex(v)
        print("  loader1: %s ops %d flen %d | loader2: %s ops %d flen %d bad %#x got %#x want %#x (%.0f s)"
              % (nm(s1[2]), s1[6], s1[5], nm(s2[2]), s2[6], s2[5], s2[7], s2[8], s2[9], time.time() - t0), flush=True)
        chk("bootstrap: loader1 OK, pool -> loader2", nm(s1[2]) == "OK" and u32(LD.POOL) == l2["ldr_path_build"])
        chk("loader2 ran in the same mount: MODS2.BIN OK, done", nm(s2[2]) == "OK" and s2[1] == 0x454E4F44)
        dw = u32(H(M["ext2_module"]["drive_word"]))
        chk("drive word %#x ('DRV' + drive)" % dw, dw >> 8 == 0x445256)
        st = [o for o in ops if o[0] == LD.OP_STORE]
        bad = [hex(o[1]) for o in st if u32(o[1]) != o[3]]
        chk("%d hook words = new%s" % (len(st), " BAD " + str(bad) if bad else ""), not bad)
        time.sleep(5)
        for s in ("key 0x13:0x04:300", 12, "rot 1", 3, "rot 1", 3, "key 0x11:0x01:300", 10,
                  "key 0x11:0x01:300", 15):
            E.step(model, s) if isinstance(s, str) else time.sleep(s)
        E.shot(model, os.path.join(shots, "main_rgb.png"))
        tl = u32(LD.TRACK_LEN)
        xs = info["ext2"]
        x = struct.unpack("<5I", E.peek(model, xs["ext2_st"], 20))
        chk("track loaded (len %d); 3-BAND data from .2EX added (ext2 status %d, added %d, %d B)"
            % (tl, x[2], x[3], x[4]), tl != 0 and x[2] == 6 and x[3] == 2)
        time.sleep(3)
        chk("deck running", "running" in E.cmd(model, "info status"))
        if link:
            pmb = os.path.join(ROOT, "work", "pm", "build")
            assert open(os.path.join(pmb, "pm.bin"), "rb").read() == open(
                os.path.join(LD.SNAP, "bin", "pm.bin"), "rb").read(), "snapshot pm.bin != work/pm/build"
            ps = {l.split()[1]: int(l.split()[0], 16) for l in open(os.path.join(pmb, "pm.syms")) if l.strip()}
            for want in (3, 4, 2):
                LS.set_master(want)
                time.sleep(6)
                h0 = u32(ps["pm_lm_hits"])
                time.sleep(2)
                n, h1 = u32(ps["pm_lm_n"]), u32(ps["pm_lm_hits"])
                E.shot(model, os.path.join(shots, "main_master%d.png" % want))
                chk("phase meter master row follows player %d (followed %d, master beats %d -> %d)"
                    % (want, n, h0, h1), n == want and h1 > h0)
        import stemsui_mk1 as SU
        E.step(model, "tap 711 37 300")                      # PERFORM
        time.sleep(4)
        E.shot(model, os.path.join(shots, "perform.png"))
        bjs = lambda: E.peek(model, info["bj"]["bj_st"], 24)
        b0 = bjs()
        x = 404                                               # swipe left on the BEAT JUMP row
        E.step(model, "touch %d 175 1" % x)
        time.sleep(0.4)
        for k in (1, 2, 3):
            E.step(model, "touch %d 175 1" % (x - 200 * k // 3))
            time.sleep(0.2)
        E.step(model, "touch %d 175 0" % (x - 200))
        time.sleep(1.5)
        b1 = bjs()
        E.shot(model, os.path.join(shots, "perform_swiped.png"))
        sw0, sw1 = struct.unpack_from("<I", b0, 20)[0], struct.unpack_from("<I", b1, 20)[0]
        chk("BEAT JUMP swipe through the touch chain: swipes %d -> %d, page %d -> %d"
            % (sw0, sw1, b0[4], b1[4]), sw1 == sw0 + 1 and b1[4] != b0[4])
        if info["stemsui"]:
            lt = SU.L["label_touch"]
            lx, ly = (lt[0] + lt[1]) // 2, (lt[2] + lt[3]) // 2
            E.step(model, "tap %d %d 250" % (lx, ly))
            time.sleep(1.5)
            E.shot(model, os.path.join(shots, "perform_stems.png"))
            m1 = E.peek(model, info["stemsui"]["stemsui_st"], 1)[0]
            E.step(model, "tap %d %d 250" % (lx, ly))
            time.sleep(1.5)
            m2 = E.peek(model, info["stemsui"]["stemsui_st"], 1)[0]
            chk("BEAT JUMP label opens STEMS (mode %d) and closes it again (mode %d)" % (m1, m2), m1 == 1 and m2 == 0)
        else:
            print("  (built without stems: STEMS checks skipped)")
        E.step(model, "tap 711 37 300")
        time.sleep(3)
        E.step(model, "tap 568 37 1500")                     # hold MENU = UTILITY
        time.sleep(3)
        E.step(model, "rot 20")
        time.sleep(1.5)
        E.shot(model, os.path.join(shots, "utility_end.png"))
        E.step(model, "tap 568 37 300")
        time.sleep(3)
        chk("deck still running after PERFORM + UTILITY", "running" in E.cmd(model, "info status"))
    finally:
        try:
            E.cmd(model, "quit")
        except OSError:
            pass
        p.wait(timeout=60)
        for q in procs:
            q.terminate()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1



if __name__ == "__main__":
    av = sys.argv[1:]
    mode = av[av.index("--mode") + 1] if "--mode" in av else "rgb"
    if av[:1] == ["build"]:
        cmd_build(mode)
    elif av[:1] == ["buildx"]:
        cmd_build_x(mode)
    elif av[:1] == ["emu"]:
        sys.exit(emu(link="--link" in av))
    else:
        print(__doc__)
