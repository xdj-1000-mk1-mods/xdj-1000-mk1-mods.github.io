#!/usr/bin/env python3
"""emu.py on the emulated Pro DJ Link segment: same CLI as emu.py, plus
DJLINK=1, multicast on loopback (macOS, see net_lo.py), and a MAC per
EMU_SLOT (02:00:00:00:00:0<slot+1>) so two decks settle their numbers.
`emu_link.py dhcp` runs the segment's DHCP server.  --kernel IMG on boot."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("DJLINK", "1")
os.environ.setdefault("GROUP", "239.77.77.9:45900")
os.environ.setdefault("CDJ_ETHER_MAC", "02:00:00:00:00:0%d" % (int(os.environ.get("EMU_SLOT", "0") or 0) + 1))
import emu as E                                                 # noqa: E402

_argv_for = E.argv_for


def _argv_lo(*a, **kw):
    argv, env = _argv_for(*a, **kw)
    i = next(k for k, x in enumerate(argv) if x.startswith("socket,id=djlink,mcast="))
    argv[i] += ",localaddr=127.0.0.1"
    return argv, env


E.argv_for = _argv_lo

if __name__ == "__main__":
    av = sys.argv[1:]
    if av[:1] == ["dhcp"]:
        g = E.argv_for("xdj1000")[1]["GROUP"]
        sys.exit(subprocess.call([sys.executable, os.path.join(HERE, "net_lo.py"),
                                  os.path.join(E.NXS2, "scripts", "net", "dhcp_server.py"), g]))
    if av[0] == "boot" and "--kernel" in av:
        k = av[av.index("--kernel") + 1]
        stick = av[av.index("--stick") + 1] if "--stick" in av else E.STICK
        p = E.start(av[1], stick=stick, kernel=k)
        print("booted pid", p.pid, flush=True)
        sys.exit(p.wait())
    sys.exit(E.main(av))
