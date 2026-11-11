/* ldr.c -- XDJ-1000 MK1 stick loader: installs RAM mods from <stick>/MODS.BIN.
 *
 * Hook: the stick mount check (models stick_mount_check) builds the path of
 * PIONEER/rekordbox/export.pdb through one pool word. ldr_path_build sits in
 * that word: it calls the stock path_build first (same result for the caller),
 * then, for the export.pdb lookup only and only once per power-on, opens
 * "<drive>:/MODS.BIN" with the firmware's own open/read/close (the same task,
 * the same ctx the mount check uses), and installs it:
 *
 *   header  u32 magic 'MODS', u32 fmt 1, u32 total bytes, u32 crc32(bytes 16..)
 *   ops     CHECK addr val | COPY dst len flags data.. | ZERO dst len flags |
 *           MEMCPY dst src len flags | STORE addr stock new flags | END
 *
 * Pass 1 validates everything (format, ranges, every CHECK and every STORE's
 * stock value) and writes nothing; any failure = nothing written. Pass 2
 * writes in file order. Blocks only inside FREE_LO..FREE_HI and never over the
 * loader / its state / the staging buffer. flags bit 0 = cached address only,
 * else cached and then the uncached P2 alias (code must reach memory for the
 * I-fetch), as deck_write.py does. Result in the state struct (STATE).
 * Every address comes from mk1/models/<model>.json (-D..., loader_mk1.py).
 */
typedef unsigned char u8;
typedef unsigned int u32;

#if !defined(PB_STOCK) || !defined(OPEN_R) || !defined(READ_DB) || !defined(CLOSE_DB) \
    || !defined(NAME_PDB) || !defined(STATE) || !defined(STAGE) || !defined(STAGE_END) \
    || !defined(FREE_LO) || !defined(FREE_HI) || !defined(LDR_LO)
#error address defines missing (mk1/loader_mk1.py)
#endif

#define R32(a) (*(volatile u32 *)(a))
#define P2(a)  (((u32)(a) & 0x1FFFFFFFu) | 0xA0000000u)

typedef int (*pb_fn)(int, const char *, char *);
typedef u32 (*open_fn)(const char *);
typedef u32 (*read_fn)(void *, u32, u32, u32);
typedef void (*close_fn)(u32);

enum { S_IDLE, S_RUN, S_OK, S_NOFILE, S_TOOBIG, S_BADHDR, S_BADCRC, S_BADOP, S_NOTSTOCK, S_MIDWAY };
enum { OP_END, OP_CHECK, OP_COPY, OP_ZERO, OP_MEMCPY, OP_STORE };

#define ST_MAGIC   0x5453444Cu           /* "LDST" */
#define DONE_MAGIC 0x454E4F44u           /* "DONE" */
#define F_MAGIC    0x53444F4Du           /* "MODS" */
#define CHUNK      0x4000u

struct ldr_state {
    u32 magic, done, status, mounts, attempts, flen, nops, bad_addr, bad_val, bad_want, crc;
#ifdef LINK_SET_STOCK
    u32 busy, via, link_calls, link_attempts, link_status;       /* loader X; via: 1 own stick, 2 linked stick */
#endif
};
#define ST ((volatile struct ldr_state *)STATE)

static u32 crc32(const u8 *p, u32 n)
{
    u32 c = 0xFFFFFFFFu;
    while (n--) {
        c ^= *p++;
        for (int k = 0; k < 8; k++)
            c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
    }
    return ~c;
}

static int dst_ok(u32 dst, u32 len)
{
    if ((dst | len) & 3u || len > FREE_HI - FREE_LO)
        return 0;
    if (dst < FREE_LO || dst > FREE_HI - len)
        return 0;
    return dst + len <= LDR_LO || dst >= STAGE_END;     /* never over loader/state/stage */
}

static void put(u32 a, u32 v, u32 flags)
{
    R32(a) = v;
    if (!(flags & 1u))
        R32(P2(a)) = v;
}

static int bad(int st, u32 a, u32 got, u32 want)
{
    ST->bad_addr = a;
    ST->bad_val = got;
    ST->bad_want = want;
    return st;
}

/* exec = 0: validate only, write nothing. Returns S_OK or the failure. */
static int walk(const u32 *p, const u32 *end, int exec)
{
    u32 n = 0;
    while (p < end) {
        u32 op = p[0], left = (u32)(end - p);
        n++;
        if (op == OP_END)
            break;
        if (op == OP_CHECK) {
            if (left < 3 || (p[1] & 3u))
                return bad(S_BADOP, (u32)p, op, 0);
            if (!exec && R32(p[1]) != p[2])
                return bad(S_NOTSTOCK, p[1], R32(p[1]), p[2]);
            p += 3;
        } else if (op == OP_COPY || op == OP_ZERO) {
            u32 dst = p[1], len = p[2], fl = p[3], words = op == OP_COPY ? len / 4u : 0;
            if (left < 4 || !dst_ok(dst, len) || words > left - 4)
                return bad(S_BADOP, (u32)p, op, dst);
            if (exec)
                for (u32 i = 0; i < len / 4u; i++)
                    put(dst + 4u * i, op == OP_COPY ? p[4 + i] : 0u, fl);
            p += 4 + words;
        } else if (op == OP_MEMCPY) {
            u32 dst = p[1], src = p[2], len = p[3], fl = p[4];
            if (left < 5 || !dst_ok(dst, len) || (src & 3u))
                return bad(S_BADOP, (u32)p, op, dst);
            if (exec)
                for (u32 i = 0; i < len / 4u; i++)
                    put(dst + 4u * i, R32(src + 4u * i), fl);
            p += 5;
        } else if (op == OP_STORE) {
            u32 a = p[1], stock = p[2], nw = p[3], fl = p[4];
            if (left < 5 || (a & 3u))
                return bad(S_BADOP, (u32)p, op, a);
            if (R32(a) != stock)
                return bad(exec ? S_MIDWAY : S_NOTSTOCK, a, R32(a), stock);
            if (exec)
                put(a, nw, fl);
            p += 5;
        } else {
            return bad(S_BADOP, (u32)p, op, 0);
        }
    }
    ST->nops = n;
    return S_OK;
}

static int load(int drive)
{
    char path[48];
    u8 *stage = (u8 *)STAGE;
    const u32 cap = STAGE_END - STAGE;
    u32 n = 0, fp, got;

#ifndef FILE_NAME
#define FILE_NAME "MODS.BIN"
#endif
    if (((pb_fn)PB_STOCK)(drive, FILE_NAME, path) != 0)
        return S_NOFILE;
    fp = ((open_fn)OPEN_R)(path);
    if (!fp)
        return S_NOFILE;
    for (;;) {
        u32 want = cap - n < CHUNK ? cap - n : CHUNK;
        if (!want) {                                  /* full: one more byte = too big */
            u8 one[4];
            got = ((read_fn)READ_DB)(one, 1, 1, fp);
            ((close_fn)CLOSE_DB)(fp);
            return got == 1 ? S_TOOBIG : S_BADHDR;    /* exactly cap: no room for sanity, refuse */
        }
        got = ((read_fn)READ_DB)(stage + n, 1, want, fp);
        if (got > want)
            got = 0;
        n += got;
        if (got < want)
            break;
    }
    ((close_fn)CLOSE_DB)(fp);
    ST->flen = n;

    const u32 *w = (const u32 *)STAGE;
    if (n < 20 || (n & 3u) || w[0] != F_MAGIC || w[1] != 1u || w[2] != n)
        return bad(S_BADHDR, n, w[0], F_MAGIC);
    ST->crc = crc32(stage + 16, n - 16);
    if (ST->crc != w[3])
        return bad(S_BADCRC, n, ST->crc, w[3]);

    int r = walk(w + 4, w + n / 4u, 0);               /* pass 1: validate, no writes */
    if (r != S_OK)
        return r;
    ST->done = DONE_MAGIC;                            /* from here on: never again this power-on */
    return walk(w + 4, w + n / 4u, 1);                /* pass 2: write */
}

#ifdef CFG_NAME
/* Stick settings (loader2 only): <stick>/MODSCFG.BIN, 20 B LE {'MCFG', 1, wave,
 * pm, check = magic ^ ver ^ wave ^ pm ^ 0x5A5A5A5A}. On every mount after the
 * mods are in: apply it (UTILITY WAVEFORM COLOR word, PHASE METER byte) and
 * note what the stick holds in CFG_STATE; the ext2 module writes the file
 * back on a track load after a change (ext2.c cfg_save). */
struct cfg_state { u32 magic, wave, pm, loads, saves, fails, status, drive; };
#define CS ((volatile struct cfg_state *)CFG_STATE)
enum { C_NONE, C_LOADED, C_NOFILE, C_BAD, C_SAVED, C_WFAIL };

static void cfg_apply(int drive)
{
    char path[48];
    u32 b[5] = { 0 }, fp, got = 0;
    if (CS->magic != 0x4746434Du) {                   /* 'MCFG' */
        for (u32 i = 0; i < sizeof(struct cfg_state) / 4u; i++)
            ((volatile u32 *)CFG_STATE)[i] = 0;
        CS->magic = 0x4746434Du;
    }
    CS->drive = (u32)drive;
    CS->wave = R32(CFG_WAVE);                         /* default: what is live (no file = no write) */
    CS->pm = *(volatile u8 *)CFG_PM;
    if (((pb_fn)PB_STOCK)(drive, CFG_NAME, path) != 0 || !(fp = ((open_fn)OPEN_R)(path))) {
        CS->status = C_NOFILE;
        return;
    }
    got = ((read_fn)READ_DB)(b, 1, sizeof b, fp);
    ((close_fn)CLOSE_DB)(fp);
    if (got != sizeof b || b[0] != 0x4746434Du || b[1] != 1u || b[2] > 2u || b[3] > 1u
        || b[4] != (b[0] ^ b[1] ^ b[2] ^ b[3] ^ 0x5A5A5A5Au)) {
        CS->status = C_BAD;
        return;
    }
    R32(CFG_WAVE) = b[2];
    *(volatile u8 *)CFG_PM = (u8)b[3];
    CS->wave = b[2];
    CS->pm = b[3];
    CS->loads++;
    CS->status = C_LOADED;
}
#endif

#ifdef LINK_SET_STOCK
/* Loader X only: the same file from the LINKED player's stick. The LINK code
 * mounts that stick as a drive through the firmware's set-drive-type routine
 * (models link_drive: one pool word, args drive letter, type 5, remote drive,
 * peer IP). ldr_link_mount sits in that word: stock call first, then, in that
 * task, while nothing is installed yet: read "<drive>:/" FILE_NAME with the
 * firmware's wide-path open/read/close (qemu: the only context found where a
 * file on the linked drive opens; mk1/link_mount_emu.py) and install it with
 * the same two passes. busy keeps the two hooks (own-stick mount task, link
 * task) off the one staging buffer; the CRC is the backstop. */
typedef u32 (*set_fn)(int, int, int, u32);
typedef u32 (*wopen_fn)(const unsigned short *, const char *, u32);
typedef u32 (*wread_fn)(void *, u32, u32, u32, u32);
typedef void (*wclose_fn)(u32, u32);

static void st_init(void)
{
    if (ST->magic != ST_MAGIC) {
        for (u32 i = 0; i < sizeof(struct ldr_state) / 4u; i++)
            ((volatile u32 *)STATE)[i] = 0;
        ST->magic = ST_MAGIC;
    }
}

static int load_link(int drive)
{
    static const char fn[] = "/" FILE_NAME;
    unsigned short w[24];
    u8 *stage = (u8 *)STAGE;
    const u32 cap = STAGE_END - STAGE;
    u32 n = 0, fp, got, k = 0;

    w[k++] = (unsigned short)(drive & 0xFF);
    w[k++] = ':';
    for (u32 i = 0; i < sizeof(fn) && k < 24; i++)
        w[k++] = (u8)fn[i];                           /* with the NUL */
    fp = ((wopen_fn)FOPEN_W)(w, "r", 0);
    if (!fp)
        return S_NOFILE;
    for (;;) {
        u32 want = cap - n < CHUNK ? cap - n : CHUNK;
        if (!want) {
            ((wclose_fn)FCLOSE_C)(fp, 0);
            return S_TOOBIG;                          /* a file that fills the stage: refuse */
        }
        got = ((wread_fn)FREAD_C)(stage + n, 1, want, fp, 0);
        if (got > want)
            got = 0;
        n += got;
        if (got < want)
            break;
    }
    ((wclose_fn)FCLOSE_C)(fp, 0);
    ST->flen = n;

    const u32 *hw = (const u32 *)STAGE;
    if (n < 20 || (n & 3u) || hw[0] != F_MAGIC || hw[1] != 1u || hw[2] != n)
        return bad(S_BADHDR, n, hw[0], F_MAGIC);
    ST->crc = crc32(stage + 16, n - 16);
    if (ST->crc != hw[3])
        return bad(S_BADCRC, n, ST->crc, hw[3]);
    int r = walk(hw + 4, hw + n / 4u, 0);             /* pass 1: validate, no writes */
    if (r != S_OK)
        return r;
    ST->done = DONE_MAGIC;
    ST->via = 2;
    return walk(hw + 4, hw + n / 4u, 1);              /* pass 2: write */
}

u32 ldr_link_mount(int drive, int type, int rdrive, u32 ip)
{
    u32 r = ((set_fn)LINK_SET_STOCK)(drive, type, rdrive, ip);
    if (type != 5)
        return r;
    st_init();
    ST->link_calls++;
    if (ST->done == DONE_MAGIC || ST->busy)
        return r;
    ST->busy = 1;
    ST->link_attempts++;
    ST->link_status = S_RUN;
    ST->link_status = (u32)load_link(drive);
    if (ST->done == DONE_MAGIC)
        ST->status = ST->link_status;                 /* the install's result, whichever way it came */
    ST->busy = 0;
    return r;
}
#endif

int ldr_path_build(int drive, const char *name, char *buf)
{
    int r = ((pb_fn)PB_STOCK)(drive, name, buf);
    if ((u32)name != NAME_PDB)
        return r;
#ifdef DRIVE_WORD
    R32(DRIVE_WORD) = 0x44525600u | ((u32)drive & 0xFFu);   /* for the 3-BAND .2EX reader */
#endif
    if (ST->magic != ST_MAGIC) {                      /* power-on junk: start clean */
        for (u32 i = 0; i < sizeof(struct ldr_state) / 4u; i++)
            ((volatile u32 *)STATE)[i] = 0;
        ST->magic = ST_MAGIC;
    }
    ST->mounts++;
#ifdef LINK_SET_STOCK
    if (ST->done == DONE_MAGIC || ST->busy)
        return r;
    ST->busy = 1;
    ST->attempts++;
    ST->status = S_RUN;
    ST->status = load(drive);
    if (ST->done == DONE_MAGIC)
        ST->via = 1;
    ST->busy = 0;
    return r;
#elif defined(CFG_NAME)
    if (ST->done != DONE_MAGIC) {
        ST->attempts++;
        ST->status = S_RUN;
        ST->status = load(drive);
    }
    if (ST->done == DONE_MAGIC && ST->status == S_OK)
        cfg_apply(drive);
    return r;
#else
    if (ST->done == DONE_MAGIC)
        return r;
    ST->attempts++;
    ST->status = S_RUN;
    ST->status = load(drive);
    return r;
#endif
}
