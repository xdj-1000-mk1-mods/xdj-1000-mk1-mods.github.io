#!/usr/bin/env python3
"""Smoke test of cdj-nxs2's own start command for the MK1: ./start.sh --model
xdj1000 (headless, no sound, a monitor socket via MAIN_ARGS for screenshots),
then: load the first track of [TRACK] from the stick (upstream's own recipe,
models/xdj1000.conf), PLAY, CUE, jog and touch, each with a screenshot.

The jog is driven with cdj-nxs2's own app code (app/controls.Jog), the same
datagrams the virtual deck app sends.

    usage: python3 mk1/smoke_xdj1000.py [MODEL]   -> work/smoke/<model>_*.png
"""
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NXS2 = os.environ.get("XDJMOD_NXS2") or os.path.abspath(os.path.join(ROOT, "..", "..", "cdj-nxs2"))
sys.path[:0] = [os.path.join(NXS2, "scripts", "run"), os.path.join(NXS2, "app"), os.path.join(NXS2, "midi")]
import cdj_monsock                                               # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "xdj1000"
PORT = 40411
MON = "/tmp/mk1-smoke-%s-mon.sock" % MODEL
OUT = os.path.join(ROOT, "work", "smoke")


def udp(payload):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(payload.encode(), ("127.0.0.1", PORT))


def mon(line):
    return cdj_monsock.command(MON, line).decode("utf-8", "replace")


def shot(name):
    ppm = os.path.join(OUT, "%s_%s.ppm" % (MODEL, name))
    mon('screendump "%s"' % ppm)
    time.sleep(0.5)
    png = ppm[:-4] + ".png"
    subprocess.run(["sips", "-s", "format", "png", ppm, "--out", png], stdout=subprocess.DEVNULL)
    os.unlink(ppm)
    print("  shot", os.path.relpath(png, ROOT), flush=True)


def jog_turn(degrees, secs=1.0):
    from controls import Jog
    import json
    face = json.load(open(os.path.join(NXS2, "app", "faces", MODEL + ".json")))
    j = Jog(udp, **face["jog"]["counter"])
    j.start()
    j.touch(True)
    n = int(secs / 0.02)
    for _ in range(n):
        j.turn(degrees / n, time.monotonic())
        time.sleep(0.02)
    time.sleep(0.3)
    j.touch(False)
    j.stop()


def main():
    os.makedirs(OUT, exist_ok=True)
    try:
        os.unlink(MON)
    except FileNotFoundError:
        pass
    env = dict(os.environ, GUI_DISPLAY="none", NOSOUND="1", CDJ_PANEL_KEYSOCK=str(PORT),
               MAIN_ARGS="-monitor unix:%s,server=on,wait=off" % MON)
    log = open(os.path.join(OUT, MODEL + "_start.log"), "w")
    t0 = time.time()
    p = subprocess.Popen(["./start.sh", "--model", MODEL], cwd=NXS2, env=env,
                         stdout=log, stderr=subprocess.STDOUT)
    try:
        if not cdj_monsock.wait_up(MON):
            raise SystemExit("start.sh: monitor never came up (see %s_start.log)" % MODEL)
        print("monitor up after %.0fs" % (time.time() - t0), flush=True)
        time.sleep(45)
        shot("1_boot")
        steps = os.environ.get("LOAD", "0x13:0x04:300:or|12|0x0e:1:0:rot|3|0x0e:1:0:rot|3|0x11:0x01:300:or|12|0x11:0x01:300:or|20")
        for s in steps.split("|"):
            udp(s) if ":" in s else time.sleep(float(s))
        shot("2_loaded_playing")
        time.sleep(3)
        shot("3_playing_later")
        udp("0x10:0x01:300:or")                    # PLAY -> pause
        time.sleep(2)
        shot("4_paused")
        time.sleep(2)
        shot("5_still_paused")
        jog_turn(360.0, 1.0)                       # one turn forward while paused
        time.sleep(1)
        shot("6_after_jog")
        udp("0x10:0x02:400:or")                    # CUE
        time.sleep(2)
        shot("7_after_cue")
        udp("710:37:200:tap")                      # touch: PERFORM
        time.sleep(3)
        shot("8_touch_perform")
        udp("0x10:0x01:300:or")                    # PLAY again
        time.sleep(3)
        shot("9_play_again")
    finally:
        try:
            mon("quit")
        except OSError:
            p.terminate()
        p.wait(timeout=60)
        print("start.sh exit", p.returncode, "after %.0fs" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
