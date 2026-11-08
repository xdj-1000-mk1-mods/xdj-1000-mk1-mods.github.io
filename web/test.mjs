// node web/test.mjs /path/to/XDJ1000.UPD  -> builds both files with core.js and checks the hashes
import { readFileSync, writeFileSync } from "node:fs";
import { buildEnabler, buildRestore, sha256 } from "./core.js";
const P = JSON.parse(readFileSync(new URL("./patch.json", import.meta.url)));
const raw = new Uint8Array(readFileSync(process.argv[2]));
if ((await sha256(raw)) !== P.upd_sha256) throw new Error("not the official v1.13 file");
let t = Date.now();
const r = await buildRestore(raw, P);
console.log("restore ", await sha256(r) === P.restore_sha256 ? "MATCH" : "DIFF", ((Date.now() - t) / 1000).toFixed(1) + " s");
t = Date.now();
const e = await buildEnabler(raw, P, (m) => console.log("  " + m), (f) => process.stdout.write("\r  " + (f * 100).toFixed(0) + "%  "));
const h = await sha256(e);
console.log("\nenabler ", h === P.enabler_sha256 ? "MATCH" : "DIFF " + h, ((Date.now() - t) / 1000).toFixed(1) + " s");
if (process.argv[3]) writeFileSync(process.argv[3], e);
