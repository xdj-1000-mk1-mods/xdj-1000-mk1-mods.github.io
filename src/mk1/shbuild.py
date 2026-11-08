"""Build a freestanding SH-4 module at a fixed address (sh-elf-gcc), as
upstream tools/utility/build.sh does: .entry at BASE, .text at BASE+0x10,
no FPU instructions, end <= END_MAX. Returns (bin bytes, {symbol: addr})."""
import hashlib
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SH = os.path.join(ROOT, "work", "sh-tools", "bin")


def _t(tool):
    return os.path.join(SH, "sh-elf-" + tool)


def build(out, name, srcs, base, end_max, defs, entry, keep=("_end",), text_off=0x10, cwd=None, extra=()):
    os.makedirs(out, exist_ok=True)
    elf = os.path.join(out, name + ".elf")
    subprocess.run([_t("gcc"), "-m4-nofpu", "-mdiv=call-div1", "-ml", "-O2", "-Wall",
                    "-ffreestanding", "-fno-builtin", *extra,
                    *["-D%s=%s" % (k, v if isinstance(v, str) else "%#xu" % v) for k, v in defs.items()],
                    "-ffunction-sections", "-fdata-sections", "-nostdlib", "-Wl,--gc-sections",
                    "-Wl,-e," + entry, "-Wl,--section-start=.entry=%#x" % base,
                    "-Wl,-Ttext=%#x" % (base + text_off), "-o", elf, *srcs, "-lgcc"], check=True, cwd=cwd)
    binf = os.path.join(out, name + ".bin")
    subprocess.run([_t("objcopy"), "-O", "binary", "-j", ".entry", "-j", ".text", "-j", ".rodata",
                    "-j", ".data", elf, binf], check=True)
    syms = {}
    for ln in subprocess.run([_t("nm"), elf], check=True, capture_output=True, text=True).stdout.splitlines():
        a, _, n = ln.split()
        if n in keep or any(n.startswith(p) for p in keep if p.endswith("_")):
            syms[n.lstrip("_")] = int(a, 16)
    dis = subprocess.run([_t("objdump"), "-d", elf], check=True, capture_output=True, text=True).stdout
    fpu = [l for l in dis.splitlines() if len(l.split("\t")) >= 3 and      # upstream build.sh's check
           re.search(r"^(f[a-z.]+|frchg|fschg)\s|fpscr|fpul", l.split("\t")[2])]
    assert not fpu, "FPU instructions in the module: %s" % fpu[:3]
    assert syms["end"] <= end_max, "module ends %#x > %#x" % (syms["end"], end_max)
    with open(os.path.join(out, name + ".syms"), "w") as f:
        for n, a in sorted(syms.items(), key=lambda x: x[1]):
            f.write("%08x %s\n" % (a, n))
    img = open(binf, "rb").read()
    assert base + len(img) <= syms["end"]
    print("%s.bin %d B at %#x..%#x (bss to end), sha256 %s" % (
        name, len(img), base, syms["end"], hashlib.sha256(img).hexdigest()), flush=True)
    return img, syms
