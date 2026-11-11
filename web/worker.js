// Runs the builds off the page's main thread. In: {file: ArrayBuffer}.
// Out: {log}, {progress}, {error}, {done: {enabler, restore, mods, mods2, modsx}}.
// Every file is only handed out if its SHA-256 equals the tested build.
import { buildEnabler, buildRestore, decodeMain, sha256 } from "./core.js";

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
const here = (f) => new URL(f, import.meta.url);
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const say = (log) => self.postMessage({ log });

// BEAT JUMP label graphics: rendered from the firmware's own digits by the
// repo's src/mk1/bjlabels.py, run unchanged in the browser (Pyodide + numpy).
async function renderLabels(dec) {
  say("loading Python (about 15 MB, once) ...");
  const { loadPyodide } = await import(PYODIDE + "pyodide.mjs");
  const py = await loadPyodide({ indexURL: PYODIDE });
  await py.loadPackage("numpy");
  say("drawing the BEAT JUMP labels from your firmware ...");
  py.FS.mkdirTree("/x/mk1/models");
  for (const f of ["bjlabels.py", "padlabels.py", "models/xdj1000_113.json"]) {
    const r = await fetch(here("../src/mk1/" + f));
    if (!r.ok) throw new Error("could not load " + f);
    py.FS.writeFile("/x/mk1/" + f, await r.text());
  }
  py.FS.writeFile("/x/main.img", dec);
  await py.runPythonAsync(`
import sys
sys.path.insert(0, "/x/mk1")
import bjlabels
bjlabels.build(bjlabels.Labels(open("/x/main.img", "rb").read()))
`);
  return py.FS.readFile("/x/work/bjswipe/build/labels.bin");
}

self.onmessage = async (ev) => {
  try {
    const P = await (await fetch(here("./patch.json"))).json();
    const S = await (await fetch(here("./stick.json"))).json();
    const raw = new Uint8Array(ev.data.file);
    say("checking the file ...");
    if ((await sha256(raw)) !== P.upd_sha256) {
      self.postMessage({ error: "This is not the official XDJ-1000 firmware 1.13 update file (XDJ1000.UPD). Nothing was built." });
      return;
    }
    const restore = await buildRestore(raw, P);
    if ((await sha256(restore)) !== P.restore_sha256) throw new Error("restore file is not the tested build");
    const enabler = await buildEnabler(raw, P, say, (f) => self.postMessage({ progress: f }));
    if ((await sha256(enabler)) !== P.enabler_sha256) throw new Error("enabler file is not the tested build");
    self.postMessage({ progress: 1 });

    const labels = await renderLabels(await decodeMain(raw, P));
    if ((await sha256(labels)) !== S.labels_sha256) throw new Error("label graphics are not the tested ones");
    const join = (pre, post) => {
      const out = new Uint8Array(pre.length + labels.length + post.length);
      out.set(pre); out.set(labels, pre.length); out.set(post, pre.length + labels.length);
      return out;
    };
    const mods2 = join(b64(S.mods2_pre_b64), b64(S.mods2_post_b64));
    const modsx = join(b64(S.modsx_pre_b64), b64(S.modsx_post_b64));
    const mods = b64(S.mods_b64);
    if ((await sha256(mods)) !== S.mods_sha256 || (await sha256(mods2)) !== S.mods2_sha256
        || (await sha256(modsx)) !== S.modsx_sha256)
      throw new Error("stick files are not the tested build");
    self.postMessage({ done: { enabler, restore, mods, mods2, modsx } },
                     [enabler.buffer, restore.buffer, mods.buffer, mods2.buffer, modsx.buffer]);
  } catch (e) {
    self.postMessage({ error: "Build stopped: " + e.message + ". Nothing to download; please open an issue." });
  }
};
