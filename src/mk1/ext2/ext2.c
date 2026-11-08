/* ext2.c -- 3-BAND waveforms from rekordbox's ANLZ0000.2EX on the MK1.
 *
 * rekordbox puts the 3-band sections PWV6 (overview) and PWV7 (centre) into
 * ANLZ0000.2EX, which the MK1 never opens; the RGB mod's 3-BAND mode looks
 * them up in the ANLZ context's extra-section index (models anlz_ctx_table:
 * ctx+IDX_OFF = u32 count, then 16-B {file off, tag, len, ptr to the raw
 * big-endian section}). After the stock .EXT parse (models ext_parse, called
 * twice per load; the index is filled by then), if the index lacks PWV6 or
 * PWV7: open the track's .EXT path (ctx+EXT_PATH_OFF) with EXT -> 2EX, read
 * the file into BUF, append index entries pointing into BUF. Upstream's own
 * emulator test appends PWV7 exactly this way (tools/rgb_detail.py).
 * Every address comes from mk1/models/<model>.json (-D..., ext2_mk1.py).
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#if !defined(IDX_OFF) || !defined(EXT_PATH_OFF) || !defined(DAT_PATH_OFF) || !defined(FOPEN_W) || !defined(FREAD_C) \
    || !defined(FCLOSE_C) || !defined(BUF) || !defined(BUF_END) || !defined(IDX_CAP) || !defined(DRIVE_WORD) || !defined(SCAN_LEN)
#error address defines missing (mk1/ext2_mk1.py)
#endif

#define R32(a) (*(volatile u32 *)(a))
#define TAG(a, b, c, d) ((u32)(a) | (u32)(b) << 8 | (u32)(c) << 16 | (u32)(d) << 24)

typedef u32 (*open_fn)(const u16 *, const char *, u32);
typedef u32 (*read_fn)(void *, u32, u32, u32, u32);
typedef void (*close_fn)(u32, u32);

enum { E_NONE, E_HAVE, E_NOPATH, E_NOFILE, E_BADFILE, E_NOSECT, E_ADDED, E_FULL };

struct ext2_state {
    u32 magic, calls, status, added, flen, last_ctx, drive, plen;
    u8 path[48];
};
struct ext2_state ext2_st = { 0x54535845u, 0, 0, 0, 0, 0, 0, 0, { 0 } };   /* "EXST", .data */
u32 ext2_save[3] = { 1, 1, 1 };                                  /* pr, ctx, sp (.data) */

static u32 be32(const u8 *p)
{
    return (u32)p[0] << 24 | (u32)p[1] << 16 | (u32)p[2] << 8 | p[3];
}

static int set(int st)
{
    ext2_st.status = st;
    return st;
}

/* the track's ANLZ path, as the loader keeps it in its own stack frame
 * (UTF-16 '/PIONEER/USBANLZ/.../ANLZ0000.DAT' or the directory alone; qemu
 * breakpoint at the parse, 2026-11-06) -- the ctx path fields are filled
 * only after the parse. Returns the length in u16 or 0. */
static u32 find_path(u32 sp, u16 *out, u32 max)
{
    static const char pre[] = "/PIONEER/USBANLZ/";
    for (u32 a = sp & ~1u; a < sp + SCAN_LEN; a += 2) {
        const volatile u16 *q = (const volatile u16 *)a;
        u32 k = 0;
        while (pre[k] && q[k] == (u8)pre[k])
            k++;
        if (pre[k])
            continue;
        u32 n = 0;
        while (n < max && q[n] && q[n] < 0x80)
            n++;
        if (n >= max || q[n])
            continue;
        for (u32 i = 0; i < n; i++)
            out[i] = q[i];
        return n;
    }
    return 0;
}

static u32 ascii_path(const char *p, u16 *out, u32 max)
{
    u32 n = 0;
    if (p[0] != '/')
        return 0;
    while (n < max && p[n] && (u8)p[n] < 0x80) {
        out[n] = (u8)p[n];
        n++;
    }
    return n < max && !p[n] ? n : 0;
}

static int add_body(u32 ctx, u32 sp);
#ifdef CFG_STATE
static void cfg_save(void);
#endif

int ext2_add(u32 ctx, u32 sp)
{
    int r = add_body(ctx, sp);
#ifdef CFG_STATE
    cfg_save();
#endif
    return r;
}

static int add_body(u32 ctx, u32 sp)
{
    u32 ix, n, want6 = 1, want7 = 1;
    ext2_st.calls++;
    if (!ctx)
        return set(E_NONE);
    ix = ctx + IDX_OFF;
    n = R32(ix);
    if (n == 0 || n > IDX_CAP)
        return set(E_NONE);                       /* first (.DAT) pass or junk */
    for (u32 k = 0; k < n; k++) {
        u32 t = R32(ix + 4 + 16 * k + 4);
        if (t == TAG('P', 'W', 'V', '6'))
            want6 = 0;
        if (t == TAG('P', 'W', 'V', '7'))
            want7 = 0;
    }
    if (!want6 && !want7)
        return set(E_HAVE);

    /* "<drive>:" + <ANLZ dir>/ANLZ0000.2EX, UTF-16 */
    u16 w[176];
    u32 drv = R32(DRIVE_WORD);                    /* 'DRV'<<8 | drive char, set by loader2 */
    drv = (drv & 0xFFFFFF00u) == 0x44525600u ? drv & 0xFFu : 'C';
    if (drv < 'A' || drv > 'z')
        drv = 'C';
    ext2_st.drive = drv;
    w[0] = (u16)drv;
    w[1] = ':';
    u32 len = find_path(sp, w + 2, 150);
    if (!len)
        len = ascii_path((const char *)(ctx + EXT_PATH_OFF), w + 2, 150);
    if (!len)
        len = ascii_path((const char *)(ctx + DAT_PATH_OFF), w + 2, 150);
    ext2_st.plen = len;
    for (u32 i = 0; i < 48; i++)
        ext2_st.path[i] = i < len ? (u8)w[2 + i] : 0;
    if (len < 18)
        return set(E_NOPATH);
    u16 *e = w + 2 + len;                         /* strip a file name: back to the last '/' */
    u32 dot = 0;
    for (u16 *q = e; q > w + 2 && q[-1] != '/'; q--)
        if (q[-1] == '.')
            dot = 1;
    if (dot)
        while (e > w + 2 && e[-1] != '/')
            e--;
    else
        *e++ = '/';
    static const char fn[] = "ANLZ0000.2EX";
    for (u32 i = 0; i <= sizeof(fn) - 1; i++)
        e[i] = (u8)fn[i];                         /* copies the NUL too */

    u32 fp = ((open_fn)FOPEN_W)(w, "r", 0);
    if (!fp)
        return set(E_NOFILE);
    u8 *buf = (u8 *)BUF;
    const u32 cap = BUF_END - BUF;
    u32 got = 0;
    for (;;) {
        u32 want = cap - got < 0x4000u ? cap - got : 0x4000u;
        if (!want)
            break;
        u32 r = ((read_fn)FREAD_C)(buf + got, 1, want, fp, 0);
        if (r > want)
            r = 0;
        got += r;
        if (r < want)
            break;
    }
    ((close_fn)FCLOSE_C)(fp, 0);
    ext2_st.flen = got;
    ext2_st.last_ctx = ctx;

    /* PMAI header, then sections {tag, u32 header len, u32 total len} (big-endian) */
    if (got < 28 || be32(buf) != TAG('I', 'A', 'M', 'P') /* 'PMAI' read BE */)
        return set(E_BADFILE);
    u32 o = be32(buf + 4), added = 0, dst = (got + 3u) & ~3u;   /* aligned copies after the file */
    while (o + 12 <= got) {
        u32 tag_be = be32(buf + o), tl = be32(buf + o + 8);
        if (tl < 12 || tl > got - o)
            break;
        if ((tag_be == 0x50575636u && want6) || (tag_be == 0x50575637u && want7)) {
            if (n >= IDX_CAP)
                return set(E_FULL);
            if (tl > cap - dst)
                break;                            /* no room: leave this one out */
            volatile u8 *d = buf + dst;
            for (u32 i = 0; i < tl; i++)
                d[i] = buf[o + i];
            u32 e = ix + 4 + 16 * n;
            R32(e + 0) = o;
            R32(e + 4) = TAG(buf[o], buf[o + 1], buf[o + 2], buf[o + 3]);   /* as stored */
            R32(e + 8) = tl;
            R32(e + 12) = (u32)buf + dst;
            dst = (dst + tl + 3u) & ~3u;
            n++;
            R32(ix) = n;                          /* count last: the entry is complete */
            added++;
            if (tag_be == 0x50575636u)
                want6 = 0;
            else
                want7 = 0;
        }
        o += tl;
    }
    ext2_st.added += added;
    return set(added ? E_ADDED : E_NOSECT);
}

#ifdef CFG_STATE
/* Stick settings, write side (read side: loader2, ldr.c cfg_apply). Runs in
 * the track-load task right after the .EXT parse, i.e. while the deck is
 * reading this stick anyway; writes <drive>:/MODSCFG.BIN only when the live
 * WAVEFORM COLOR / PHASE METER values differ from what the stick holds,
 * and gives up after 3 failed writes this power-on. */
typedef u32 (*write_fn)(const void *, u32, u32, u32, u32);
struct cfg_state { u32 magic, wave, pm, loads, saves, fails, status, drive; };
#define CS ((volatile struct cfg_state *)CFG_STATE)

static void cfg_save(void)
{
    if (CS->magic != 0x4746434Du || CS->fails >= 3)
        return;                                   /* loader2 has not seen this stick */
    u32 wave = R32(CFG_WAVE), pm = *(volatile u8 *)CFG_PM;
    if (wave > 2u || pm > 1u || (wave == CS->wave && pm == CS->pm))
        return;
    static const char fn[] = "/MODSCFG.BIN";
    u16 w[16];
    u32 drv = CS->drive;
    if (drv < 'A' || drv > 'z')
        drv = 'C';
    w[0] = (u16)drv;
    w[1] = ':';
    for (u32 i = 0; i < sizeof(fn); i++)
        w[2 + i] = (u8)fn[i];                     /* with the NUL */
    u32 b[5] = { 0x4746434Du, 1u, wave, pm, 0 };
    b[4] = b[0] ^ b[1] ^ b[2] ^ b[3] ^ 0x5A5A5A5Au;
    u32 fp = ((open_fn)FOPEN_W)(w, "w", 0);
    if (!fp) {
        CS->fails++;
        CS->status = 5;                           /* C_WFAIL */
        return;
    }
    u32 n = ((write_fn)FWRITE_C)(b, 1, sizeof b, fp, 0);
    ((close_fn)FCLOSE_C)(fp, 0);
    if (n != sizeof b) {
        CS->fails++;
        CS->status = 5;
        return;
    }
    CS->wave = wave;
    CS->pm = pm;
    CS->saves++;
    CS->status = 4;                               /* C_SAVED */
}
#endif
