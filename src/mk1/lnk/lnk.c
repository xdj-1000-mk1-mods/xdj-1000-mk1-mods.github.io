/* lnk.c -- colour / 3-band waveforms for tracks loaded over Pro DJ Link.
 *
 * The MK1 gets a LINK track's blue waveform and grid from the other player's
 * database service, never its colour data. But the other player's stick is a
 * drive here (models link_drive, "D:"), and the media task that opens the
 * track's audio can read any file on it (qemu, mk1/link_aopen_emu.py). Hook:
 * that task's fopen_w pool word. After the stock open of "D:/<audio path>"
 * (the second open of the same path in a row: the deck opens the loaded
 * track several times, and peeks once at the next one in the list):
 *   1. scan D:/PIONEER/rekordbox/export.pdb for the track row whose file path
 *      equals <audio path> -> its analyze path (DeviceSQL track row: subtype
 *      0x24, 21 u16 string offsets at +0x5e, [14] analyze path, [20] file path)
 *   2. read PWV4 + PWV5 from that ANLZ0000.EXT and PWV6 + PWV7 from .2EX
 *      straight into the colour slots (raw section, tag word written last)
 *   3. LINK_FLAG = 1: the snapshot code leaves the slots alone and the
 *      centre painter uses them once their length fits the loaded track
 *      (rgb_mk1.py LINK_GUARD / COPY5 patch).
 * Any other open (own stick, another track) clears LINK_FLAG first.
 * Every address comes from mk1/models/<model>.json (-D..., lnk_mk1.py). */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#if !defined(FOPEN_W) || !defined(FREAD_C) || !defined(FCLOSE_C) || !defined(LINK_FLAG) || !defined(SLOT4) \
    || !defined(SLOT5) || !defined(SLOT6) || !defined(SLOT7) || !defined(SLOT4_MAX) || !defined(SLOT5_MAX) \
    || !defined(SLOT6_MAX) || !defined(SLOT7_MAX)
#error address defines missing (mk1/lnk_mk1.py)
#endif

#define R32(a) (*(volatile u32 *)(a))
#define TAG(a, b, c, d) ((u32)(a) | (u32)(b) << 8 | (u32)(c) << 16 | (u32)(d) << 24)
#define PATHMAX 300
#define PAGE 4096u
#define MAXPAGES 8192u                  /* 32 MB of export.pdb, then give up */

typedef u32 (*open_fn)(const u16 *, const char *, u32);
typedef u32 (*read_fn)(void *, u32, u32, u32, u32);
typedef void (*close_fn)(u32, u32);

enum { L_NONE, L_OK, L_NOPDB, L_NOROW, L_NOANLZ, L_NODATA };

struct lnk_state {
    u32 magic, opens, dopens, fetches, status, pages, got4, got5, got6, got7, same;
    u16 anlz[64];
};
struct lnk_state lnk_st = { 0x4B4E494Cu };      /* "LINK" */
static u16 last[PATHMAX];                       /* path of the previous open */
static u16 done[PATHMAX];                       /* path the slots were last filled for */
static u8 page[PAGE];

static u32 rd(void *b, u32 n, u32 fp, u32 desc)
{
    u32 r = ((read_fn)FREAD_C)(b, 1, n, fp, desc);
    return r > n ? 0 : r;
}

static u32 wlen(const u16 *s) { u32 n = 0; while (n < PATHMAX - 1 && s[n]) n++; return n; }

static int weq(const u16 *a, const u16 *b)
{
    for (u32 i = 0; i < PATHMAX; i++) {
        if (a[i] != b[i]) return 0;
        if (!a[i]) return 1;
    }
    return 0;
}

static void wcpy(u16 *d, const u16 *s)
{
    u32 i = 0;
    for (; i < PATHMAX - 1 && s[i]; i++) d[i] = s[i];
    d[i] = 0;
}

static u32 u16at(const u8 *p) { return (u32)p[0] | (u32)p[1] << 8; }
static u32 be32(const u8 *p) { return (u32)p[0] << 24 | (u32)p[1] << 16 | (u32)p[2] << 8 | p[3]; }

/* DeviceSQL string at s (inside [.., end)): chars into out (max), 0 = none */
static u32 dstr(const u8 *s, const u8 *end, u16 *out, u32 max)
{
    if (s >= end) return 0;
    u32 h = s[0], n, wide = 0;
    const u8 *c;
    if (h & 1) {                                    /* short ASCII: length incl. this byte */
        n = h >> 1;
        if (n < 2) return 0;
        n -= 1; c = s + 1;
    } else {
        if (s + 4 > end || (h != 0x40 && h != 0x90)) return 0;
        n = u16at(s + 1);
        if (n < 5) return 0;
        n -= 4; c = s + 4;
        if (h == 0x90) { wide = 1; n >>= 1; }
    }
    if (n > max || c + (wide ? 2 * n : n) > end) return 0;
    for (u32 i = 0; i < n; i++) out[i] = wide ? (u16)u16at(c + 2 * i) : c[i];
    return n;
}

/* the analyze path of the track whose file path is t (tn chars); 0 = not found */
static u32 pdb_lookup(const u16 *t, u32 tn, u32 desc, u16 *out, u32 max)
{
    static const u16 pdb[] = { 'D', ':', '/', 'P', 'I', 'O', 'N', 'E', 'E', 'R', '/', 'r', 'e', 'k', 'o', 'r', 'd',
                               'b', 'o', 'x', '/', 'e', 'x', 'p', 'o', 'r', 't', '.', 'p', 'd', 'b', 0 };
    static u16 tmp[PATHMAX];
    u32 fp = ((open_fn)FOPEN_W)(pdb, "r", desc), found = 0;
    if (!fp) { lnk_st.status = L_NOPDB; return 0; }
    for (u32 pg = 0; pg < MAXPAGES && !found; pg++) {
        if (rd(page, PAGE, fp, desc) != PAGE) break;
        lnk_st.pages = pg + 1;
        if (!pg || be32(page + 8) != 0) continue;   /* file header / not a tracks page (type 0, LE = BE) */
        for (u32 r = 0x28; r + 0x5e + 42 <= PAGE; r += 2) {
            if (u16at(page + r) != 0x24) continue;
            u32 sf = r + u16at(page + r + 0x5e + 40);
            if (sf >= PAGE) continue;
            u32 n = dstr(page + sf, page + PAGE, tmp, PATHMAX - 1);
            if (n != tn) continue;
            u32 i = 0;
            while (i < n && tmp[i] == t[i]) i++;
            if (i != n) continue;
            found = dstr(page + r + u16at(page + r + 0x5e + 28), page + PAGE, out, max);
            if (found) break;
        }
    }
    ((close_fn)FCLOSE_C)(fp, desc);
    if (!found) lnk_st.status = L_NOROW;
    return found;
}

/* read up to two sections of one ANLZ file into their slots; returns a bit per section */
static u32 fetch(const u16 *path, u32 desc, u32 tag_a, u32 slot_a, u32 max_a, u32 tag_b, u32 slot_b, u32 max_b)
{
    u8 h[12];
    u32 fp = ((open_fn)FOPEN_W)(path, "r", desc), got = 0;
    if (!fp) return 0;
    if (rd(h, 12, fp, desc) == 12 && h[0] == 'P' && h[1] == 'M' && h[2] == 'A' && h[3] == 'I') {
        u32 skip = be32(h + 4);
        skip = skip >= 12 ? skip - 12 : 0;
        for (;;) {
            while (skip) {                          /* no seek on this path: read past it */
                u32 n = skip < PAGE ? skip : PAGE;
                if (rd(page, n, fp, desc) != n) goto out;
                skip -= n;
            }
            if (got == 3 || rd(h, 12, fp, desc) != 12) break;
            u32 tag = TAG(h[0], h[1], h[2], h[3]), tl = be32(h + 8), slot = 0, bit = 0;
            if (tl < 12) break;
            if (tag == tag_a && tl <= max_a) { slot = slot_a; bit = 1; }
            if (tag == tag_b && tl <= max_b) { slot = slot_b; bit = 2; }
            if (!slot || (got & bit)) { skip = tl - 12; continue; }
            u8 *d = (u8 *)slot;
            R32(slot) = 0;                          /* not valid while it is written */
            for (u32 i = 4; i < 12; i++) d[i] = h[i];
            u32 body = tl - 12, at = 12;
            while (body) {
                u32 n = body < 0x4000u ? body : 0x4000u;
                if (rd(d + at, n, fp, desc) != n) goto out;
                at += n; body -= n;
            }
            R32(slot) = tag;                        /* publish */
            got |= bit;
        }
    }
out:
    ((close_fn)FCLOSE_C)(fp, desc);
    return got;
}

static void fill(const u16 *path, u32 desc)
{
    static u16 w[PATHMAX];
    u16 *ap = w + 2;
    u32 n = pdb_lookup(path + 2, wlen(path + 2), desc, ap, PATHMAX - 8);
    lnk_st.got4 = lnk_st.got5 = lnk_st.got6 = lnk_st.got7 = 0;
    if (!n) return;
    ap[n] = 0;
    for (u32 i = 0; i < 63; i++) lnk_st.anlz[i] = i < n ? ap[i] : 0;
    if (n < 5 || ap[n - 4] != '.') { lnk_st.status = L_NOANLZ; return; }
    w[0] = 'D'; w[1] = ':';
    ap[n - 3] = 'E'; ap[n - 2] = 'X'; ap[n - 1] = 'T';
    u32 g = fetch(w, desc, TAG('P', 'W', 'V', '4'), SLOT4, SLOT4_MAX, TAG('P', 'W', 'V', '5'), SLOT5, SLOT5_MAX);
    lnk_st.got4 = g & 1; lnk_st.got5 = g >> 1;
    ap[n - 3] = '2'; ap[n - 2] = 'E'; ap[n - 1] = 'X';
    u32 g2 = fetch(w, desc, TAG('P', 'W', 'V', '6'), SLOT6, SLOT6_MAX, TAG('P', 'W', 'V', '7'), SLOT7, SLOT7_MAX);
    lnk_st.got6 = g2 & 1; lnk_st.got7 = g2 >> 1;
    lnk_st.status = (g | g2) ? L_OK : L_NODATA;
}

u32 lnk_open(const u16 *path, const char *mode, u32 desc)
{
    u32 fp = ((open_fn)FOPEN_W)(path, mode, desc);
    lnk_st.opens++;
    int link = fp && path[0] == 'D' && path[1] == ':' && path[2] == '/';
    int again = weq(path, last);
    wcpy(last, path);
    if (!link) {                                    /* own stick (or a failed open): no LINK data */
        if (R32(LINK_FLAG)) { R32(LINK_FLAG) = 0; done[0] = 0; }
        return fp;
    }
    lnk_st.dopens++;
    if (!again) return fp;                          /* first open of this path: may be the next-track peek */
    if (weq(path, done)) { lnk_st.same++; return fp; }
    R32(LINK_FLAG) = 0;
    R32(SLOT4) = 0; R32(SLOT5) = 0; R32(SLOT6) = 0; R32(SLOT7) = 0;
    lnk_st.fetches++;
    lnk_st.status = L_NONE;
    fill(path, desc);
    wcpy(done, path);
    if (lnk_st.status == L_OK) R32(LINK_FLAG) = 1;
    return fp;
}
