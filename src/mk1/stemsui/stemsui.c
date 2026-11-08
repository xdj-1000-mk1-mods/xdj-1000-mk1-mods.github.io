/* stemsui.c -- STEMS on the MK1 PERFORM screen (UI for mk1/stems_mk1.py's mixer).
 *
 * Tapping the BEAT JUMP row label switches that row to
 *     STEMS -- [VOCALS] [DRUMS] [BASS] [OTHER] [ALL ON] [BACK]
 * (BACK or the label again = beat jump). A stem pad toggles its bit in the
 * mixer's mute mask (PMASK bit i = stem i muted; white text = on, dim =
 * muted); ALL ON clears the mask. Mutes stay when the view is closed: the
 * row label then reads STEMS in red. Inert (the label tap goes to stock)
 * unless the mixer is installed (its entry table at SM_BASE names sm_fread).
 * Drawing as ksui.c: on every full-screen UI present while PERFORM is up,
 * the pad images (mk1/stemsui_assets.py) are copied over the row; the deck
 * re-blits its own pads all the time, so view off = stock pads back.
 * Every address comes from mk1/models/<model>.json (-D...).
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define R32(a) (*(volatile u32 *)(a))
#define R8(a)  (*(volatile u8 *)(a))
#define UNCACHED(p) (((u32)(p) & 0x1FFFFFFFu) | 0xA0000000u)

#if !defined(MODEW) || !defined(MODE_PERFORM) || !defined(PMASK) || !defined(SM_BASE) \
    || !defined(SM_SIG) || !defined(IMG) || !defined(ROW_Y0) || !defined(ROW_Y1) \
    || !defined(PADS) || !defined(LABEL) || !defined(TITLE_XY)
#error address defines missing (mk1/stemsui_mk1.py)
#endif
#include "stemsui_layout.h"

static const u16 pad_x[6][2] = PADS;          /* BEAT JUMP pads 1..6: x0, x1 */
static const u16 label[4] = LABEL;            /* x0 x1 y0 y1 */
static const u16 title_xy[2] = TITLE_XY;

struct stemsui_state {
    u8 mode, prev, held, pad;
    u32 draws, taps, toggles;
};
struct stemsui_state stemsui_st;              /* zero at install */

static int mixer(void)
{
    return R32(SM_BASE) == SM_SIG;
}

static int in(int x, int y, int x0, int x1, int y0, int y1)
{
    return x >= x0 && x <= x1 && y >= y0 && y <= y1;
}

int stemsui_on_touch(int down, int x, int y)
{
    struct stemsui_state *s = &stemsui_st;
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
    if (R32(MODEW) != MODE_PERFORM || !mixer())
        return 0;
    if (in(x, y, label[0], label[1], label[2], label[3])) {
        s->mode ^= 1;
        s->held = 1;
        s->taps++;
        return 1;
    }
    if (!s->mode || y < ROW_Y0 || y > ROW_Y1)
        return 0;
    for (int i = 0; i < 6; i++) {
        if (x < pad_x[i][0] || x > pad_x[i][1])
            continue;
        s->held = 1;
        s->taps++;
        if (i < 4) {
            R8(PMASK) = (u8)((R8(PMASK) ^ (1u << i)) & 15u);
            s->toggles++;
        } else if (i == 4) {
            R8(PMASK) = 0;                    /* ALL ON */
            s->toggles++;
        } else {
            s->mode = 0;                      /* BACK */
        }
        return 1;
    }
    return 0;                                 /* the gaps between pads: stock */
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

static const u32 on_off[4] = { IMG_ON0_OFF, IMG_ON1_OFF, IMG_ON2_OFF, IMG_ON3_OFF };
static const u32 mu_off[4] = { IMG_MU0_OFF, IMG_MU1_OFF, IMG_MU2_OFF, IMG_MU3_OFF };

void stemsui_on_flush(u32 dev, u32 req)
{
    (void)dev;
    u32 mask = R8(PMASK) & 15u;
    if (!mixer() || R32(MODEW) != MODE_PERFORM || (!stemsui_st.mode && !mask))
        return;
    const u32 *w = (const u32 *)R32(req);    /* the full-screen UI present (as pm.c) */
    if (!w || w[13] != 0x4C || w[16] != 0x58) return;
    if ((w[27] >> 24) != 0x82 || w[29] != 0x032001E0u) return;
    u16 *lay = (u16 *)UNCACHED(w[14]);
    int stride = (int)w[17];
    if (stride < 800 || stride > 1024) return;
    if (!stemsui_st.mode) {                   /* closed with a stem muted: red label */
        blit(lay, stride, title_xy[0], title_xy[1], IMG_ALERT_OFF, IMG_ALERT_W, IMG_ALERT_H);
        return;
    }
    for (int i = 0; i < 4; i++)
        blit(lay, stride, pad_x[i][0], ROW_Y0, (mask >> i) & 1 ? mu_off[i] : on_off[i], IMG_ON0_W, IMG_ON0_H);
    blit(lay, stride, pad_x[4][0], ROW_Y0, IMG_ALL_OFF, IMG_ALL_W, IMG_ALL_H);
    blit(lay, stride, pad_x[5][0], ROW_Y0, IMG_BACK_OFF, IMG_BACK_W, IMG_BACK_H);
    blit(lay, stride, title_xy[0], title_xy[1], IMG_TITLE_OFF, IMG_TITLE_W, IMG_TITLE_H);
    stemsui_st.draws++;
}
