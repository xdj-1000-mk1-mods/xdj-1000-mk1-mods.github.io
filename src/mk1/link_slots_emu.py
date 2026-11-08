#!/usr/bin/env python3
"""qemu: where does the MK1 keep each linked player's status?

Cold-boots the stock MK1 on an emulated Pro DJ Link segment with three
software players (cdj-nxs2 scripts/net/tempo_master.py) as players 2, 3, 4 at
distinct tempi (121 / 133 / 145 BPM), then searches RAM for their BPM*100
values and the master flag, once with player 3 master and once with player 4.

    link_slots_emu.py [SECONDS_TO_LEASE]   -> work/link/slots_*.bin + summary
"""
import os
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("DJLINK", "1")
os.environ.setdefault("GROUP", "239.77.77.9:45900")
import emu as E                                                 # noqa: E402

_argv_for = E.argv_for


def _argv_lo(*a, **kw):                                 # macOS: multicast on loopback (net_lo.py)
    argv, env = _argv_for(*a, **kw)
    i = next(k for k, x in enumerate(argv) if x.startswith("socket,id=djlink,mcast="))
    argv[i] += ",localaddr=127.0.0.1"
    return argv, env


E.argv_for = _argv_lo

NET = os.path.join(E.NXS2, "scripts", "net")
LO = os.path.join(HERE, "net_lo.py")
OUT = os.path.join(os.path.dirname(HERE), "work", "link")
MODEL = "xdj1000"
PLAYERS = {2: 121.0, 3: 133.0, 4: 145.0}
CTL = {n: 47100 + n for n in PLAYERS}
REGION = (0x0D200000, 0x00100000)


def peek(a, n):
    g, out = E.Gdb(MODEL), bytearray()
    try:
        for o in range(0, n, 0x800):
            out += g.rd(a + o, min(0x800, n - o))
    finally:
        g.detach()
    return bytes(out)


def tell(n, cmd):
    subprocess.run([sys.executable, os.path.join(NET, "tempo_master.py"), "--tell", str(CTL[n])] + cmd.split(),
                   check=False, capture_output=True)


def scan(tag):
    a0, n = REGION
    d = peek(a0, n)
    open(os.path.join(OUT, "slots_%s.bin" % tag), "wb").write(d)
    print("== %s" % tag)
    for pn, bpm in PLAYERS.items():
        v = struct.pack("<H", int(bpm * 100))
        hits = [a0 + i for i in range(0, n - 1, 2) if d[i:i + 2] == v]
        print("  player %d bpm %d: %s" % (pn, bpm * 100, " ".join("%#x" % h for h in hits[:12])))
    st = 0x0D2D04F0 - a0
    print("  0x0d2d04f0: flags+9 %#04x bpm+0x10 %d" % (d[st + 9], struct.unpack_from("<H", d, st + 0x10)[0]))
    return d


def start_players(group, master=3):
    """dhcp_server + software players 2/3/4 on the segment (multicast on loopback);
    player `master` holds the master role. Returns the processes."""
    procs = []
    logs = open(os.path.join(OUT, "slots_net.log"), "ab")
    procs.append(subprocess.Popen([sys.executable, LO, os.path.join(NET, "dhcp_server.py"), group],
                                  stdout=logs, stderr=subprocess.STDOUT, cwd=E.NXS2))
    for pn, bpm in PLAYERS.items():
        procs.append(subprocess.Popen(
            [sys.executable, LO, os.path.join(NET, "tempo_master.py"), group, "--number", str(pn), "--bpm", str(bpm),
             "--name", "CDJ-2000nexus", "--control", str(CTL[pn]), "--log", os.path.join(OUT, "slots_p%d.log" % pn)],
            stdout=logs, stderr=subprocess.STDOUT, cwd=NET))
    time.sleep(1)
    set_master(master)
    return procs


def set_master(n):
    """new master first, then the others step down: with no master on the
    segment for a moment, the deck takes the role itself and keeps it"""
    tell(n, "role on")
    time.sleep(0.5)
    for pn in PLAYERS:
        if pn != n:
            tell(pn, "role off")


def group_now():
    return E.argv_for(MODEL)[1].get("GROUP")


def main(av):
    lease = float(av[0]) if av else 150
    os.makedirs(OUT, exist_ok=True)
    argv, env = E.argv_for(MODEL)
    group = env.get("GROUP")
    print("segment", group, flush=True)
    procs = start_players(group, master=3)
    p = E.start(MODEL)
    try:
        time.sleep(lease)
        set_master(3)
        time.sleep(5)
        scan("m3")
        set_master(4)
        time.sleep(5)
        scan("m4")
        print("deck", E.cmd(MODEL, "info status").strip().splitlines()[-1])
    finally:
        try:
            E.cmd(MODEL, "quit")
        except OSError:
            pass
        p.wait(timeout=60)
        for q in procs:
            q.terminate()


if __name__ == "__main__":
    main(sys.argv[1:])
