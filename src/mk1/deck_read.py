#!/usr/bin/env python3
"""READ-ONLY access to a connected XDJ-1000 MK1 over its USB debug shell.

CLAUDE.md rule 6: the first hardware contact is read-only. This client can
only send three things, and has no code path for anything else:
  $CDJ          the shell handshake
  ?V            firmware version query
  <a>,<n-1>BR   byte read, address inside RAM 0x08000000-0x0FFFFFFF, n <= 64
The command table these use is identical on MK1 v1.13 and the 700 v1.15
(same offset 0x0806dc34, same 41 commands, same argc/radix; the BR and ?V
handlers are the same code), and upstream tools/xdj700_usb_shell.py uses
them on the 700 / XDJ-1000MK2. Reports: MK1's HID descriptor has no report
IDs, 64-byte output and 20-byte input reports; commands are ASCII.
Sessions are paced 30 s apart like upstream (rapid re-opens wedge the
deck's USB).

    deck_read.py descriptor          HID report descriptor (no commands sent)
    deck_read.py version             handshake + ?V
    deck_read.py br ADDR COUNT       hex address, hex count (1..40)
    deck_read.py check               version + compare RAM with the unpacked image
                                     + the play-position word twice
"""
import os
import re
import struct
import sys
import time

import hid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VID, PID, USAGE = 0x08E4, 0x01A6, 0x01
STAMP = os.path.expanduser("~/.xdj1000_shell_last")
PACE = 30.0


def _pace():
    try:
        wait = PACE - (time.time() - os.path.getmtime(STAMP))
    except OSError:
        return
    if wait > 0:
        print("pacing: %.0f s since the last session" % wait, flush=True)
        time.sleep(wait)


def _stamp():
    open(STAMP, "w").write(str(time.time()))


def open_deck():
    devs = [d for d in hid.enumerate(VID, PID) if d.get("usage") == USAGE]
    if len({d.get("serial_number") for d in devs}) > 1:
        sys.exit("more than one XDJ-1000 connected")
    if not devs:
        sys.exit("no XDJ-1000 shell interface (vid %04x pid %04x usage %d)" % (VID, PID, USAGE))
    _pace()
    _stamp()
    return _Dev(devs[0]["path"])


class _Dev:
    """same C calls as upstream's `hid` package (hid_write / hid_read /
    hid_get_report_descriptor), through the `hidapi` binding in our venv"""
    def __init__(self, path):
        self.d = hid.device()
        self.d.open_path(path)
        self.d.set_nonblocking(1)

    def write(self, b):
        return self.d.write(bytes(b))

    def read(self, n, timeout=100):
        return bytes(self.d.read(n, timeout))

    def get_report_descriptor(self):
        return bytes(self.d.get_report_descriptor())

    def close(self):
        self.d.close()


def _send(h, text):
    """the ONLY write to the device: one allow-listed command"""
    ok = text == b"$CDJ\r" or text == b"?V\r" or re.fullmatch(rb"[0-9a-f]{7,8},[0-9a-f]{1,2}BR\r", text)
    if not ok:
        raise SystemExit("deck_read: refusing to send %r (read-only client)" % text)
    if text.endswith(b"BR\r"):
        a, n = text[:-3].split(b",")
        a, n = int(a, 16), int(n, 16) + 1
        if not (0x08000000 <= a and a + n <= 0x10000000 and 1 <= n <= 40):
            raise SystemExit("deck_read: BR outside RAM / too long: %#x +%d" % (a, n))
    # MK1's descriptor: no report IDs, 64-byte output report -> hidapi wants
    # a 0x00 report number, then the 64 bytes (upstream's 26-byte form fits
    # the 700's descriptor, not this one)
    h.write(b"\x00" + (text + b"\x00").ljust(64, b"\x00"))


def _drain(h, secs, until=None):
    out = bytearray()
    end = time.time() + secs
    while time.time() < end:
        c = h.read(64, timeout=100)
        if c:
            out.extend(c)
            if until and until(bytes(out)):
                break
        else:
            time.sleep(0.02)
    return bytes(out)


def text(b):
    return b.replace(b"\x00", b"").decode("ascii", "replace")


def handshake(h):
    _send(h, b"$CDJ\r")
    return _drain(h, 1.5)


def version(h):
    _send(h, b"?V\r")
    return _drain(h, 2.0)


def br(h, addr, n):
    """n bytes from addr (n <= 40); parsed from the shell's hex reply"""
    _send(h, b"%x,%xBR\r" % (addr, n - 1))
    pat = re.compile(rb"\b[0-9A-Fa-f]{2}\b")

    def done(o):
        t = o.replace(b"\x00", b"")
        return len(pat.findall(t.split(b"BR")[-1])) >= n and (b"\n" in t or b"\r" in t)
    raw = _drain(h, 6.0, done)
    t = raw.replace(b"\x00", b"")
    vals = pat.findall(t.split(b"BR")[-1]) if b"BR" in t else pat.findall(t)
    if len(vals) < n:
        raise IOError("short BR reply for %#x+%d: %r" % (addr, n, text(raw)[:200]))
    return bytes(int(v, 16) for v in vals[-n:]), raw


def main(av):
    if not av or av[0] not in ("descriptor", "version", "br", "check"):
        print(__doc__)
        return 0
    if av[0] == "descriptor":
        devs = [d for d in hid.enumerate(VID, PID)]
        for d in devs:
            print("usage %#06x/%#04x interface %d path %s" % (d["usage_page"], d["usage"], d["interface_number"], d["path"]))
        h = open_deck()
        try:
            print("report descriptor:", h.get_report_descriptor().hex(" "))
        finally:
            h.close()
        return 0
    h = open_deck()
    try:
        r = handshake(h)
        print("handshake reply: %r" % text(r)[:200])
        if av[0] == "version":
            print("?V reply: %r" % text(version(h))[:300])
        elif av[0] == "br":
            a, n = int(av[1], 16), int(av[2], 16)
            d, raw = br(h, a, n)
            print("%#x: %s" % (a, d.hex(" ")))
        else:
            check(h)
    finally:
        h.close()
    return 0


def check(h):
    import hashlib
    print("?V reply: %r" % text(version(h))[:300], flush=True)
    img = open(os.path.join(ROOT, "work", "MAIN_mk1_113.img"), "rb").read()
    print("image sha256 %s" % hashlib.sha256(img).hexdigest()[:16])
    # 1. RAM == unpacked image: version record + code the mods touch
    for a, n, what in ((0x08000740, 32, "version record"), (0x08000800, 32, "MAIN entry"),
                       (0x08CF94F4, 4, "touch hook slot"), (0x08C37F14, 4, "flush hook slot"),
                       (0x08D790A8, 4, "UTILITY pool"), (0x080B7C48, 32, "beat jump table"),
                       (0x08CDD630, 2, "key-word store")):
        d, _ = br(h, a, n)
        want = img[a - 0x08000000:a - 0x08000000 + n]
        print("%-16s %#x: %s  %s" % (what, a, "== image" if d == want else "DIFFERS", d.hex(" ")[:47]), flush=True)
    # 2. play position: two reads 1 s apart (+4 = track length), 1/150 s
    for i in range(2):
        d, _ = br(h, 0x0EAE6DBC, 8)
        pos, ln = struct.unpack("<II", d)
        print("play position 0x0eae6dbc = %d (%.2f s), length %d (%.2f s)  t=%.1f" % (
            pos, pos / 150, ln, ln / 150, time.time()), flush=True)
        if i == 0:
            time.sleep(1.0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
