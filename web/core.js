// XDJ-1000 MK1 enabler builder: a byte-exact JavaScript port of the repo's
// Python build (src/tools/fwtool.py, src/tools/lzss_boot.py, src/mk1/build_mk1.py,
// src/mk1/restore_mk1.py). Runs in a Web Worker (index.html) or in Node (test.mjs).
// Input: the official XDJ1000.UPD (v1.13). Output: only accepted if its SHA-256
// equals the tested build, so a port bug can never hand out a flashable file.

const N = 4096, F = 18, THR = 2, R0 = N - F;

export function lzssDecode(src, cap) {
  const rb = new Uint8Array(N); rb.fill(0x20, 0, R0);
  const out = new Uint8Array(cap);                     // caller knows the size
  let o = 0, r = R0, p = 0;
  const n = src.length;
  while (p < n) {
    let fl = src[p]; p++;
    for (let b = 0; b < 8; b++) {
      if (p >= n) return out.subarray(0, o);
      if (fl & 1) {
        const c = src[p]; p++;
        if (o >= cap) throw new Error("LZSS output overflow");
        out[o] = c; o++; rb[r] = c; r = (r + 1) & (N - 1);
      } else {
        if (p + 1 >= n) return out.subarray(0, o);
        const b1 = src[p], b2 = src[p + 1]; p += 2;
        const i = b1 | ((b2 & 0xF0) << 4), L = (b2 & 0x0F) + THR + 1;
        if (o + L > cap) throw new Error("LZSS output overflow");
        for (let k = 0; k < L; k++) {
          const c = rb[(i + k) & (N - 1)];
          out[o] = c; o++; rb[r] = c; r = (r + 1) & (N - 1);
        }
      }
      fl >>= 1;
    }
  }
  return out.subarray(0, o);
}

// Okumura-compatible encoder with lazy matching: the same choices, in the same
// order, as lzss_boot.encode (hash chains keyed by 3 bytes, newest 4096 tried,
// chains trimmed by 4096 past 8192 entries). Plain loops, no closures.
let BL = 0, BD = 0;                                    // bestAt results
function bestAt(V, nV, head, p) {
  BL = 0; BD = 0;
  if (p + 2 >= nV) return;
  const c = head.get((V[p] << 16) | (V[p + 1] << 8) | V[p + 2]);
  if (c === undefined) return;
  const stop = c.length > 4096 ? c.length - 4096 : 0;
  for (let x = c.length - 1; x >= stop; x--) {
    const j = c[x], d = p - j;
    if (d > N) break;
    let l = 3;
    while (l < F && p + l < nV && V[j + l] === V[p + l]) l++;
    if (l > BL) { BL = l; BD = d; if (l === F) break; }
  }
}

export function lzssEncode(data, progress) {
  const base = N;                                      // bytes(N-R0) zeros + R0 spaces
  const nV = base + data.length;
  const V = new Uint8Array(nV);
  V.fill(0x20, N - R0, base);
  V.set(data, base);
  const head = new Map();
  for (let j = 0; j < base - 2; j++) {
    const k = (V[j] << 16) | (V[j + 1] << 8) | V[j + 2];
    let c = head.get(k);
    if (c === undefined) { c = []; head.set(k, c); }
    c.push(j);
  }
  const out = new Uint8Array(data.length + (data.length >> 3) + 16);
  const chunk = new Uint8Array(16);
  let o = 0, flags = 0, nf = 0, cl = 0, p = base, tick = 0;
  let havePend = false, pl = 0, pd = 0;
  while (p < nV) {
    let bl, bd;
    if (havePend) { bl = pl; bd = pd; havePend = false; }
    else { bestAt(V, nV, head, p); bl = BL; bd = BD; }
    if (bl >= 3 && bl < F) {
      bestAt(V, nV, head, p + 1);
      if (BL > bl) { havePend = true; pl = BL; pd = BD; bl = 0; bd = 0; }
    }
    let step;
    if (bl >= 3) {
      const r = (R0 + p - base) & (N - 1), i = (r - bd) & (N - 1);
      chunk[cl] = i & 0xFF; chunk[cl + 1] = ((i >> 4) & 0xF0) | (bl - THR - 1); cl += 2;
      step = bl;
    } else {
      flags |= 1 << nf; chunk[cl] = V[p]; cl++; step = 1;
    }
    nf++;
    if (nf === 8) {
      out[o] = flags; o++;
      for (let q = 0; q < cl; q++) { out[o] = chunk[q]; o++; }
      flags = 0; nf = 0; cl = 0;
    }
    const end = p + step < nV - 2 ? p + step : nV - 2;
    for (let k = p; k < end; k++) {
      const key = (V[k] << 16) | (V[k + 1] << 8) | V[k + 2];
      let c = head.get(key);
      if (c === undefined) { c = []; head.set(key, c); }
      c.push(k);
      if (c.length > 8192) c.splice(0, 4096);
    }
    p += step;
    tick++;
    if (progress && (tick & 262143) === 0) progress((p - base) / data.length);
  }
  if (nf) { out[o] = flags; o++; for (let q = 0; q < cl; q++) { out[o] = chunk[q]; o++; } }
  return out.slice(0, o);
}

// ---------------------------------------------------------------- UPD container
const ascii = (u8, a, b) => { let s = ""; for (let i = a; i < b; i++) s += String.fromCharCode(u8[i]); return s; };
const hexv = (c) => (c <= 57 ? c - 48 : c - 55);

function crc16x(u8, n) {
  let c = 0;
  for (let i = 0; i < n; i++) {
    c ^= u8[i] << 8;
    for (let k = 0; k < 8; k++) c = c & 0x8000 ? ((c << 1) ^ 0x1021) & 0xFFFF : (c << 1) & 0xFFFF;
  }
  return c;
}

export function parseUPD(raw) {
  let e1 = 0; while (!(raw[e1] === 13 && raw[e1 + 1] === 10)) e1++;
  let e2 = e1 + 2; while (!(raw[e2] === 13 && raw[e2 + 1] === 10)) e2++;
  const lens = [parseInt(ascii(raw, 0, e1), 10), parseInt(ascii(raw, e1 + 2, e2), 10)];
  let off = e2 + 2; const secs = [];
  for (const n of lens) { secs.push(raw.subarray(off, off + n)); off += n; }
  if (off !== raw.length) throw new Error("trailing bytes after the sections");
  return secs;
}

// MAIN section: preamble up to the first 'S2', 32-byte S2 records, then the
// terminator text and a 2-byte CRC. -> {pre, recs:[addr], img, post}
export function parseMain(blob) {
  let first = 0; while (!(blob[first] === 0x53 && blob[first + 1] === 0x32)) first++;
  const pre = blob.subarray(0, first);
  const recs = []; const img = new Uint8Array(8 << 20).fill(0xFF);
  let p = first, hi = 0;
  while (blob[p] === 0x53 && blob[p + 1] === 0x32) {
    const cnt = (hexv(blob[p + 2]) << 4) | hexv(blob[p + 3]);
    let a = 0; for (let k = 0; k < 6; k++) a = (a << 4) | hexv(blob[p + 4 + k]);
    const nb = cnt - 4;
    for (let k = 0; k < nb; k++) img[a + k] = (hexv(blob[p + 10 + 2 * k]) << 4) | hexv(blob[p + 11 + 2 * k]);
    recs.push([a, nb]); hi = Math.max(hi, a + nb);
    p += 4 + cnt * 2 + 2;                                  // 'S2' cc + bytes + CRLF
  }
  const post = blob.subarray(p, blob.length - 2);
  return { pre, recs, img: img.subarray(0, hi), post };
}

const HEXB = new TextEncoder().encode("0123456789ABCDEF");
// No closures over mutable counters in the hot loops: V8's optimiser (Node 26 /
// Chrome) produced wrong bytes on the first pass with them (seen in test.mjs).
export function emitMain(m) {
  let size = m.pre.length + m.post.length + 2;
  for (let r = 0; r < m.recs.length; r++) size += 4 + (m.recs[r][1] + 4) * 2 + 2;   // 'S2' cc, addr+data+sum, CRLF
  const out = new Uint8Array(size), img = m.img;
  out.set(m.pre, 0);
  let o = m.pre.length;
  for (let r = 0; r < m.recs.length; r++) {
    const a = m.recs[r][0], nb = m.recs[r][1], cnt = nb + 4;
    const a2 = (a >> 16) & 255, a1 = (a >> 8) & 255, a0 = a & 255;
    let sum = cnt + a2 + a1 + a0;
    out[o] = 0x53; out[o + 1] = 0x32;
    out[o + 2] = HEXB[cnt >> 4]; out[o + 3] = HEXB[cnt & 15];
    out[o + 4] = HEXB[a2 >> 4]; out[o + 5] = HEXB[a2 & 15];
    out[o + 6] = HEXB[a1 >> 4]; out[o + 7] = HEXB[a1 & 15];
    out[o + 8] = HEXB[a0 >> 4]; out[o + 9] = HEXB[a0 & 15];
    o += 10;
    for (let k = 0; k < nb; k++) {
      const v = img[a + k];
      sum += v;
      out[o] = HEXB[v >> 4]; out[o + 1] = HEXB[v & 15];
      o += 2;
    }
    const c = (~sum) & 0xFF;
    out[o] = HEXB[c >> 4]; out[o + 1] = HEXB[c & 15]; out[o + 2] = 13; out[o + 3] = 10;
    o += 4;
  }
  out.set(m.post, o); o += m.post.length;
  const c = crc16x(out, o); out[o] = c & 255; out[o + 1] = c >> 8;
  if (o + 2 !== size) throw new Error("emit size mismatch");
  return out;
}

function assemble(blobs) {
  const hdr = new TextEncoder().encode(blobs.map((b) => b.length + "\r\n").join(""));
  const out = new Uint8Array(hdr.length + blobs.reduce((s, b) => s + b.length, 0));
  out.set(hdr); let o = hdr.length;
  for (const b of blobs) { out.set(b, o); o += b.length; }
  return out;
}

function setBanner(pre, from, to) {
  const s = ascii(pre, 0, pre.length), k = s.indexOf("MAINVer" + from);
  if (k < 0) throw new Error("MAIN banner Ver" + from + " not found");
  const out = pre.slice();
  for (let i = 0; i < 4; i++) out[k + 7 + i] = to.charCodeAt(i);
  return out;
}

export async function sha256(u8) {
  const h = await crypto.subtle.digest("SHA-256", u8);
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------------------------------------------------------------- the builds
export async function buildRestore(raw, P) {
  const secs = parseUPD(raw), m = parseMain(secs[0]);
  m.pre = setBanner(m.pre, "1.13", P.restore_banner);
  return assemble([emitMain(m), secs[1]]);
}

// The verified decoded MAIN image (for the stick's label graphics).
export async function decodeMain(raw, P) {
  const m = parseMain(parseUPD(raw)[0]), [hdr, ln] = P.block;
  const dec = lzssDecode(m.img.subarray(hdr + 4, hdr + 4 + ln), P.out_len);
  if ((await sha256(dec)) !== P.image_sha256) throw new Error("MAIN does not unpack to the verified v1.13 image");
  return dec;
}

export async function buildEnabler(raw, P, log = () => {}, progress = () => {}) {
  const secs = parseUPD(raw), m = parseMain(secs[0]);
  if (emitMain(m).length !== secs[0].length) throw new Error("MAIN does not re-emit to its own size");
  const [hdr, ln] = P.block;
  const len0 = m.img[hdr] | (m.img[hdr + 1] << 8) | (m.img[hdr + 2] << 16) | (m.img[hdr + 3] * 2 ** 24);
  if (len0 !== ln) throw new Error("MAIN block 1 not where the v1.13 file has it");
  log("unpacking MAIN ...");
  const dec = lzssDecode(m.img.subarray(hdr + 4, hdr + 4 + ln), P.out_len);
  if ((await sha256(dec)) !== P.image_sha256) throw new Error("MAIN does not unpack to the verified v1.13 image");
  log("applying the stick loader (" + P.runs.length + " small changes + " + P.tail.length / 2 + " B boot copier) ...");
  const img = new Uint8Array(P.out_len); img.set(dec);
  for (const [off, hex] of P.runs) for (let i = 0; i < hex.length / 2; i++) img[off + i] = parseInt(hex.substr(2 * i, 2), 16);
  for (let i = 0; i < P.tail.length / 2; i++) img[dec.length + i] = parseInt(P.tail.substr(2 * i, 2), 16);
  if ((await sha256(img)) !== P.out_image_sha256) throw new Error("patched image is not the tested one");
  log("compressing (the slow part) ...");
  const st = lzssEncode(img, progress);
  const back = lzssDecode(st, P.out_len + 1);
  if (back.length !== img.length || (await sha256(back)) !== P.out_image_sha256) throw new Error("compression round-trip failed");
  // write_block: [u32 len][stream][u16 byte sum], 0xFF up to the old end
  const endOld = hdr + 4 + ln + 2, endNew = hdr + 4 + st.length + 2;
  if (endNew > m.img.length) throw new Error("compressed MAIN does not fit the flash slot");
  for (let i = endOld; i < endNew; i++) if (m.img[i] !== 0xFF) throw new Error("compressed MAIN would overwrite data");
  const b = m.img;
  b[hdr] = st.length & 255; b[hdr + 1] = (st.length >> 8) & 255; b[hdr + 2] = (st.length >> 16) & 255; b[hdr + 3] = (st.length >>> 24) & 255;
  b.set(st, hdr + 4);
  let s = 0; for (let i = hdr; i < hdr + 4 + st.length; i++) s += b[i];
  b[hdr + 4 + st.length] = s & 255; b[hdr + 5 + st.length] = (s >> 8) & 255;
  for (let i = endNew; i < endOld; i++) b[i] = 0xFF;
  m.pre = setBanner(m.pre, "1.13", P.banner);
  log("writing the update file ...");
  return assemble([emitMain(m), secs[1]]);
}
