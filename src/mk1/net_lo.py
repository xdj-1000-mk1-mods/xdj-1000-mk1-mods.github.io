#!/usr/bin/env python3
"""Run a cdj-nxs2 net script (tempo_master.py, dhcp_server.py) with its
multicast on loopback: macOS refuses multicast on Wi-Fi to processes without
Local Network permission (EHOSTUNREACH). Pair with qemu's
-netdev socket,mcast=...,localaddr=127.0.0.1.   net_lo.py SCRIPT ARGS..."""
import runpy
import socket
import struct
import sys

LO = socket.inet_aton("127.0.0.1")
_set = socket.socket.setsockopt


class LoSocket(socket.socket):
    def setsockopt(self, level, opt, val, *rest):
        if level == socket.IPPROTO_IP and opt == socket.IP_ADD_MEMBERSHIP and isinstance(val, bytes):
            val = val[:4] + LO
            _set(self, socket.IPPROTO_IP, socket.IP_MULTICAST_IF, LO)
            _set(self, socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        return _set(self, level, opt, val, *rest)


socket.socket = LoSocket
script = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, script.rsplit("/", 1)[0])
runpy.run_path(script, run_name="__main__")
