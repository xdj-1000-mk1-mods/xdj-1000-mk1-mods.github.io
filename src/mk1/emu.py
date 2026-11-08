#!/usr/bin/env python3
"""Drive an XDJ deck (xdj1000 = MK1 v1.13, xdj700 = v1.15) in cdj-nxs2's QEMU.

The QEMU command line comes from cdj-nxs2's own launcher (launcher.deck.command),
then: headless, a monitor socket, CDJ_TOUCH=1, our test stick instead of
extract/usbmedia3.img, and optionally the tbcov plugin (mk1/tools/tbcov.c) and
a saved state to start from. Everything it writes goes to work/emu/.

    emu.py boot  MODEL [--stick IMG]            power on, keep running (Ctrl-C/quit)
    emu.py cmd   MODEL "<monitor command>"
    emu.py shot  MODEL OUT.png
    emu.py tap   MODEL X Y [MS]        | touch MODEL X Y 0/1 | key MODEL 0xOFF:0xVAL[:MS]
    emu.py save  MODEL NAME                     state -> work/emu/MODEL/NAME.vm
    emu.py run   MODEL NAME SECS OUT [--script "tap 100 200; wait 1; key 0x13:0x04:300"]
                 [--kernel IMG] [--stick IMG]  (restore with the stick the state was saved with)
                 restore NAME (or power on when NAME is '-'), run the script, keep
                 running to SECS, quit; with OUT != '-' the tbcov plugin writes
                 the executed TBs to OUT; --kernel boots a patched MAIN image
Every step of --script is one of: wait S | tap X Y [MS] | touch X Y 0/1 | rot N |
key 0xOFF:0xVAL[:MS] | sendkey KEY [MS] | shot FILE | mem ADDR LEN FILE (physical,
pmemsave) | hold ADDR MASK MS (gdbstub: keep bits set) | peek ADDR LEN FILE.
"""
import os
import shlex
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                                   # xdj-mod-studio/
NXS2 = os.environ.get("XDJMOD_NXS2") or os.path.abspath(os.path.join(ROOT, "..", "..", "cdj-nxs2"))
WORK = os.path.join(ROOT, "work", "emu")
STICK = os.path.join(ROOT, "work", "testusb", "test_usb.img")
PLUGIN = os.path.join(ROOT, "work", "libtbcov.dylib")
PORTS = {"xdj1000": 40311, "xdj700": 40312}                    # panel key UDP ports
GDB = {"xdj1000": 41311, "xdj700": 41312}                      # gdbstub TCP ports
# EMU_SLOT=n runs a second, independent deck of the same model (its own monitor
# socket, panel and gdb ports +100*n, logs): a background job and a foreground
# test can then use one model at the same time.
SLOT = int(os.environ.get("EMU_SLOT", "0") or 0)


def tag(model):
    return model if not SLOT else "%s-s%d" % (model, SLOT)


def kport(model):
    return PORTS[model] + 100 * SLOT


def gport(model):
    return GDB[model] + 100 * SLOT

sys.path[:0] = [NXS2, os.path.join(NXS2, "scripts", "run")]
from launcher import deck as D, model as M                      # noqa: E402
from launcher.layout import Layout                              # noqa: E402
import cdj_monsock                                              # noqa: E402


def mon_path(model):
    return "/tmp/mk1-%s-mon.sock" % tag(model)


def argv_for(model, stick=STICK, plugin_out=None, incoming=None, kernel=None, paused=False):
    lay, m = Layout(), M.load(model)
    # EMU_AUDIODEV (e.g. "driver=wav,path=/abs/out.wav") records the deck's audio
    snd = dict(NOSOUND="0", AUDIODEV=os.environ["EMU_AUDIODEV"]) if os.environ.get("EMU_AUDIODEV") \
        else dict(NOSOUND="1")
    env = dict(os.environ, GUI_DISPLAY=os.environ.get("EMU_DISPLAY", "none"), CDJ_TOUCH="1", **snd,
               CDJ_PANEL_KEYSOCK=str(kport(model)))
    argv, env = D.command(lay, m, env)
    i = next(k for k, a in enumerate(argv) if a.startswith("if=none,id=usbstk,"))
    argv[i] = "if=none,id=usbstk,file=%s,format=raw,snapshot=on" % stick
    argv[argv.index("-serial") + 1] = "file:%s/%s.serial.log" % (WORK, tag(model))
    if kernel:                                 # a patched image instead of extract/<model>/
        argv[argv.index("-kernel") + 1] = os.path.abspath(kernel)
    if paused:                                 # CPU stopped until monitor 'cont'
        argv.append("-S")
    argv += ["-gdb", "tcp:127.0.0.1:%d" % gport(model),
             "-monitor", "unix:%s,server=on,wait=off" % mon_path(model),
             "-global", "migration.store-global-state=off"]
    if plugin_out:
        argv += ["-plugin", "%s,out=%s" % (PLUGIN, os.path.abspath(plugin_out))]
    if incoming:
        argv += ["-incoming", "file:%s" % incoming]
    return argv, env


def start(model, **kw):
    os.makedirs(os.path.join(WORK, model), exist_ok=True)
    try:
        os.unlink(mon_path(model))
    except FileNotFoundError:
        pass
    argv, env = argv_for(model, **kw)
    log = open(os.path.join(WORK, "%s.qemu.log" % tag(model)), "ab")
    p = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT, cwd=NXS2)
    if not cdj_monsock.wait_up(mon_path(model)):
        p.kill()
        raise SystemExit("monitor never came up; see work/emu/%s.qemu.log" % tag(model))
    return p


def cmd(model, line, wait=120):
    """A monitor command; retries refused connects (the monitor accepts
    nobody while an -incoming state is still loading)."""
    deadline = time.time() + wait
    while True:
        try:
            return cdj_monsock.command(mon_path(model), line).decode("utf-8", "replace")
        except OSError:
            if time.time() >= deadline:
                raise
            time.sleep(0.3)


def udp(model, payload):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(payload.encode(), ("127.0.0.1", kport(model)))


class Gdb:
    """Minimal GDB remote protocol client for QEMU's gdbstub: attaching stops
    the VM; m/M read/write guest memory (virtual = physical here, MMU off);
    c runs, 0x03 stops, D detaches (the VM runs on)."""
    def __init__(self, model):
        self.s = socket.create_connection(("127.0.0.1", gport(model)), timeout=10)
        self.s.sendall(b"+")
        self.req("?")

    def _read_packet(self):
        buf = b""
        while True:
            c = self.s.recv(1)
            if not c:
                raise OSError("gdbstub closed")
            if c == b"$":
                break
        while True:
            c = self.s.recv(1)
            if c == b"#":
                self.s.recv(2)
                self.s.sendall(b"+")
                return buf.decode()
            buf += c

    def send(self, cmd):
        pkt = "$%s#%02x" % (cmd, sum(cmd.encode()) & 0xFF)
        self.s.sendall(pkt.encode())
        while self.s.recv(1) != b"+":
            pass

    def req(self, cmd):
        self.send(cmd)
        return self._read_packet()

    def rd(self, addr, n):
        return bytes.fromhex(self.req("m%x,%x" % (addr, n)))

    def wr(self, addr, data):
        assert self.req("M%x,%x:%s" % (addr, len(data), data.hex())) == "OK"

    def cont(self):
        self.send("c")

    def stop(self):
        self.s.sendall(b"\x03")
        self._read_packet()

    def detach(self):
        self.req("D")
        self.s.close()


def hold(model, addr, mask, ms, every=0.01):
    """Keep `mask` set in the byte at `addr` for `ms`, re-asserting it every
    `every` s of host time (firmware may rebuild the byte each frame), then
    clear it."""
    g = Gdb(model)
    t_end = time.time() + ms / 1000.0
    while True:
        b = g.rd(addr, 1)[0]
        g.wr(addr, bytes([b | mask]))
        g.cont()
        time.sleep(every)
        g.stop()
        if time.time() >= t_end:
            break
    b = g.rd(addr, 1)[0]
    g.wr(addr, bytes([b & ~mask & 0xFF]))
    g.detach()


def peek(model, addr, n):
    g = Gdb(model)
    d = g.rd(addr, n)
    g.detach()
    return d


def shot(model, out):
    out = os.path.abspath(out)                 # QEMU's cwd is cdj-nxs2
    ppm = out[:-4] + ".ppm" if out.endswith(".png") else out
    cmd(model, "screendump %s" % ppm)
    for _ in range(50):
        if os.path.exists(ppm) and os.path.getsize(ppm) > 0:
            break
        time.sleep(0.1)
    if out.endswith(".png"):
        subprocess.run(["sips", "-s", "format", "png", ppm, "--out", out],
                       stdout=subprocess.DEVNULL, check=True)
        os.unlink(ppm)


def save(model, name):
    path = os.path.join(WORK, model, name + ".vm")
    cmd(model, "stop")
    cmd(model, 'migrate "file:%s.part"' % path)
    while True:
        out = cmd(model, "info migrate")
        if "completed" in out or "failed" in out or "cancelled" in out:
            break
        time.sleep(0.5)
    if "completed" not in out:
        cmd(model, "cont")
        raise SystemExit("save failed: " + out)
    os.replace(path + ".part", path)
    cmd(model, "cont")
    return path


def step(model, s):
    a = shlex.split(s)
    if not a:
        return
    if a[0] == "wait":
        time.sleep(float(a[1]))
    elif a[0] == "tap":
        udp(model, "%d:%d:%d:tap" % (int(a[1]), int(a[2]), int(a[3]) if len(a) > 3 else 150))
    elif a[0] == "touch":
        udp(model, "%d:%d:%d:touch" % (int(a[1]), int(a[2]), int(a[3])))
    elif a[0] == "key":
        p = a[1].split(":")
        udp(model, "%s:%s:%s:or" % (p[0], p[1], p[2] if len(p) > 2 else "150"))
    elif a[0] == "rot":                        # rot N: select knob, N detents (report 0x0E)
        n = int(a[1])
        for _ in range(abs(n)):
            udp(model, "0x0e:%d:0:rot" % (1 if n > 0 else -1))
            time.sleep(0.15)
    elif a[0] == "sendkey":                    # the window keyboard (board.c keymap)
        cmd(model, "sendkey %s %s" % (a[1], a[2] if len(a) > 2 else "150"))
    elif a[0] == "hold":                        # hold ADDR MASK MS (gdbstub)
        hold(model, int(a[1], 0), int(a[2], 0), int(a[3]))
    elif a[0] == "peek":                        # peek ADDR LEN FILE (gdbstub, virtual)
        open(a[3], "wb").write(peek(model, int(a[1], 0), int(a[2], 0)))
    elif a[0] == "load":                        # load ADDR FILE: write a blob (gdbstub)
        addr, data = int(a[1], 0), open(a[2], "rb").read()
        g = Gdb(model)
        for o in range(0, len(data), 0x200):
            g.wr(addr + o, data[o:o + 0x200])
        g.detach()
    elif a[0] == "poke16":                      # poke16 ADDR VALUE (gdbstub, one store)
        g = Gdb(model)
        g.wr(int(a[1], 0), int(a[2], 0).to_bytes(2, "little"))
        g.detach()
    elif a[0] == "poke32":                      # poke32 ADDR VALUE (gdbstub, one store)
        g = Gdb(model)
        g.wr(int(a[1], 0), int(a[2], 0).to_bytes(4, "little"))
        g.detach()
    elif a[0] in ("fill", "check"):             # fill ADDR LEN BYTE | check ADDR LEN BYTE FILE
        addr, n, v = int(a[1], 0), int(a[2], 0), int(a[3], 0)
        g, bad = Gdb(model), []
        for o in range(0, n, 0x200):               # QEMU gdbstub packets are <= 4 KB of hex
            k = min(0x200, n - o)
            if a[0] == "fill":
                g.wr(addr + o, bytes([v]) * k)
            else:
                d = g.rd(addr + o, k)
                bad += [addr + o + i for i, x in enumerate(d) if x != v]
        g.detach()
        if a[0] == "check":
            open(a[4], "w").write("%d changed of %d at %#x\n%s\n" % (
                len(bad), n, addr, " ".join("%#x" % x for x in bad[:64])))
    elif a[0] == "sample":                      # sample ADDR LEN MS FILE: read every ~20 ms
        addr, n, ms = int(a[1], 0), int(a[2], 0), int(a[3])
        g, t0, rows = Gdb(model), time.time(), []
        while time.time() - t0 < ms / 1000.0:
            rows.append("%.3f %s" % (time.time() - t0, g.rd(addr, n).hex()))
            g.cont()
            time.sleep(0.02)
            g.stop()
        g.detach()
        open(a[4], "w").write("\n".join(rows) + "\n")
    elif a[0] == "shot":
        shot(model, a[1])
    elif a[0] == "save":                        # save NAME: the state, as work/emu/MODEL/NAME.vm
        save(model, a[1])
    elif a[0] == "mem":
        cmd(model, "pmemsave %s %s \"%s\"" % (a[1], a[2], os.path.abspath(a[3])))
    else:
        raise SystemExit("unknown step %r" % s)


def main(av):
    op, model = av[0], av[1]
    if op == "boot":
        stick = av[av.index("--stick") + 1] if "--stick" in av else STICK
        p = start(model, stick=stick)
        print("booted pid", p.pid, "monitor", mon_path(model), flush=True)
        p.wait()
    elif op == "cmd":
        print(cmd(model, av[2]))
    elif op == "shot":
        shot(model, av[2])
    elif op in ("tap", "touch", "key"):
        step(model, " ".join(av[0:1] + av[2:]))
    elif op == "save":
        print(save(model, av[2]))
    elif op == "run":
        name, secs, out = av[2], float(av[3]), av[4]
        script = av[av.index("--script") + 1] if "--script" in av else ""
        kernel = av[av.index("--kernel") + 1] if "--kernel" in av else None
        stick = av[av.index("--stick") + 1] if "--stick" in av else STICK
        vm = None if name == "-" else os.path.join(WORK, model, name + ".vm")   # '-': power on
        p = start(model, plugin_out=None if out == "-" else out, incoming=vm, kernel=kernel,
                  stick=os.path.abspath(stick))
        t0 = time.time()
        for _ in range(240):                                   # restore done?
            if "running" in cmd(model, "info status"):
                break
            time.sleep(0.25)
        t0 = time.time()
        for s in script.split(";"):
            step(model, s.strip())
        while time.time() - t0 < secs:
            time.sleep(0.2)
        cmd(model, "quit")
        p.wait(timeout=60)
        print("ran %s from %s for %.1fs -> %s" % (model, name, time.time() - t0, out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
