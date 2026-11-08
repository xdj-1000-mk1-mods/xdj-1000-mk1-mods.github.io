/* ksui.c -- KEY SHIFT on the MK1 PERFORM screen (UI for mk1/keyshift_mk1.py).
 *
 * The 700 mod (upstream tools/perform_pads.py: KEY SHIFT tab, ksstep, rkjd)
 * on MK1's layout: tapping the HOT CUE row label switches that row to
 *     KEY SHIFT -- [ - ] [ +2 ] [ + ] [ RESET ] [ BACK ]
 * (BACK or the label again = hot cues). Rules kept from the 700:
 *   - inert unless the key shift engine is installed (the deck's store into
 *     the key word is NOPed) and MASTER TEMPO is on; the value pad then
 *     reads N/A or MT OFF,
 *   - any MASTER TEMPO change resets the key to 0 (upstream freeze fix:
 *     MT off -> key -> MT on froze a deck),
 *   - the deck clears the key word when a track (re)loads: put ours back.
 * Key word: 0x40000000 | round(2^(s/12) * 2^20); 0x00100000 = no shift.
 * Drawing: on every full-screen UI present while PERFORM is up and the mode
 * is on, the pad images (mk1/ksui_assets.py) are copied over the row; the
 * deck re-blits its own pads all the time, so mode off = stock pads back.
 * Every address comes from mk1/models/<model>.json (-D...).
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef signed char s8;

#define R32(a) (*(volatile u32 *)(a))
#define R16(a) (*(volatile u16 *)(a))
#define R8(a)  (*(volatile u8 *)(a))
#define UNCACHED(p) (((u32)(p) & 0x1FFFFFFFu) | 0xA0000000u)

#if !defined(MODEW) || !defined(MODE_PERFORM) || !defined(MTW) || !defined(KEY_WORD) \
    || !defined(SITE) || !defined(SITE_NOP) || !defined(IMG) || !defined(ROW_Y0) \
    || !defined(ROW_Y1) || !defined(PADS) || !defined(LABEL) || !defined(TITLE_XY) || !defined(KWORDS)
#error address defines missing (mk1/ksui_mk1.py)
#endif
#include "ksui_layout.h"

#define KEY_OFF 0x00100000u

static const u16 pad_x[5][2] = PADS;          /* A B C REC CALL: x0, x1 */
static const u16 label[4] = LABEL;            /* x0 x1 y0 y1 */
static const u16 title_xy[2] = TITLE_XY;
static const u32 kwords[13] = KWORDS;         /* -6..+6 */

struct ksui_state {
    u8 mode, prev, held, mt_last;
    s8 key, pad[3];
    u32 draws, taps, steps, resets, reasserts;
};
struct ksui_state ksui_st;                    /* zero at install; mt_last set by the installer */

static int engine(void)
{
    return R16(SITE) == SITE_NOP;
}

static void set_key(int k)
{
    if (k < -6) k = -6;
    if (k > 6) k = 6;
    ksui_st.key = (s8)k;
    R32(KEY_WORD) = k ? kwords[k + 6] : KEY_OFF;
}

static int in(int x, int y, int x0, int x1, int y0, int y1)
{
    return x >= x0 && x <= x1 && y >= y0 && y <= y1;
}

int ksui_on_touch(int down, int x, int y)
{
    struct ksui_state *s = &ksui_st;
    if (!down) {
        s->prev = 0;
        s->held = 0;
        return 0;
    }
    if (s->held)                              /* our press: keep it */
        return 1;
    if (s->prev)                              /* began elsewhere: not ours */
        return 0;
    s->prev = 1;
    if (R32(MODEW) != MODE_PERFORM)
        return 0;
    if (in(x, y, label[0], label[1], label[2], label[3])) {
        s->mode ^= 1;
        s->held = 1;
        s->taps++;
        return 1;
    }
    if (!s->mode || y < ROW_Y0 || y > ROW_Y1)
        return 0;
    for (int i = 0; i < 5; i++) {
        if (x < pad_x[i][0] || x > pad_x[i][1])
            continue;
        s->held = 1;
        s->taps++;
        if (i == 4) {                         /* BACK */
            s->mode = 0;
        } else if (i != 1 && engine() && R8(MTW) == 1) {
            s->steps++;
            set_key(i == 0 ? s->key - 1 : i == 2 ? s->key + 1 : 0);
        }
        return 1;
    }
    return 0;                                 /* the gaps between pads: stock */
}

static void watch(void)
{
    struct ksui_state *s = &ksui_st;
    u8 mt = R8(MTW);
    if (mt != s->mt_last) {                   /* any MT change: key back to 0 */
        s->mt_last = mt;
        if (s->key) {
            s->resets++;
            if (engine())
                set_key(0);
            else
                s->key = 0;
        }
    }
    if (s->key && engine() && R32(KEY_WORD) != kwords[s->key + 6]) {
        s->reasserts++;                       /* a track load cleared it */
        R32(KEY_WORD) = kwords[s->key + 6];
    }
}

static void blit(u16 *lay, int stride, int x0, int y0, u32 off, int w, int h)
{
    const u16 *src = (const u16 *)(IMG + off);
    for (int y = 0; y < h; y++) {
        u16 *d = lay + (y0 + y) * stride + x0;
        const u16 *p = src + y * w;
        for (int x = 0; x < w; x++)
            d[x] = p[x];
    }
}

static const u32 b_off[13] = {
    IMG_BM6_OFF, IMG_BM5_OFF, IMG_BM4_OFF, IMG_BM3_OFF, IMG_BM2_OFF, IMG_BM1_OFF, IMG_BP0_OFF,
    IMG_BP1_OFF, IMG_BP2_OFF, IMG_BP3_OFF, IMG_BP4_OFF, IMG_BP5_OFF, IMG_BP6_OFF };

void ksui_on_flush(u32 dev, u32 req)
{
    (void)dev;
    watch();
    if (!ksui_st.mode || R32(MODEW) != MODE_PERFORM)
        return;
    const u32 *w = (const u32 *)R32(req);    /* the full-screen UI present (as pm.c) */
    if (!w || w[13] != 0x4C || w[16] != 0x58) return;
    if ((w[27] >> 24) != 0x82 || w[29] != 0x032001E0u) return;
    u16 *lay = (u16 *)UNCACHED(w[14]);
    int stride = (int)w[17];
    if (stride < 800 || stride > 1024) return;
    u32 b = !engine() ? IMG_BNA_OFF : R8(MTW) != 1 ? IMG_BMT_OFF : b_off[ksui_st.key + 6];
    blit(lay, stride, pad_x[0][0], ROW_Y0, IMG_A_OFF, IMG_A_W, IMG_A_H);
    blit(lay, stride, pad_x[1][0], ROW_Y0, b, IMG_BP0_W, IMG_BP0_H);
    blit(lay, stride, pad_x[2][0], ROW_Y0, IMG_C_OFF, IMG_C_W, IMG_C_H);
    blit(lay, stride, pad_x[3][0], ROW_Y0, IMG_REC_OFF, IMG_REC_W, IMG_REC_H);
    blit(lay, stride, pad_x[4][0], ROW_Y0, IMG_CALL_OFF, IMG_CALL_W, IMG_CALL_H);
    blit(lay, stride, title_xy[0], title_xy[1], IMG_TITLE_OFF, IMG_TITLE_W, IMG_TITLE_H);
    ksui_st.draws++;
}
