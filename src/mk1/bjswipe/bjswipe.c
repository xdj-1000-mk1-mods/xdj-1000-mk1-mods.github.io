/* bjswipe.c -- swipe the MK1's stock BEAT JUMP row for sizes 1..64 beats.
 *
 * The 700 mod (tools/perform_pads.py): tap a pad to jump, drag the row
 * > 48 px to page the sizes 1-2-4 -> 4-8-16 -> 16-32-64 (left = bigger,
 * one step per drag). On MK1 the pads are stock and the stock jump fires on
 * PRESS, so a press on the row is held back from the stock hit-tester and
 * decided here: a drag pages (no jump), a release without one calls the
 * stock jump handler with the pad's code (guards/quantize all stock).
 * Paging rewrites the beats of the six jump-table entries (directions are
 * untouched) and copies that page's labels into the six pad sprites (3
 * styles each; the PERFORM screen re-blits them by itself). The labels
 * (mk1/bjlabels.py) sit at LBL: [page][code 1..6][style] = the digit band
 * rows; page 0 is the stock band. Sprites are written through the uncached
 * alias so the 2DG engine reads the new pixels.
 * All addresses come from mk1/models/<model>.json (-D...).
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define R32(a) (*(volatile u32 *)(a))

#if !defined(MODEW) || !defined(MODE_PERFORM) || !defined(BJ_TAB) || !defined(BJ_HANDLER) \
    || !defined(ROW_Y0) || !defined(ROW_Y1) || !defined(PAD_X) || !defined(LBL) \
    || !defined(SPR) || !defined(STYLE_STRIDE) || !defined(BAND_OFF) || !defined(BAND_BYTES)
#error address defines missing (mk1/bjswipe_mk1.py)
#endif

#define SWIPE_PX 48                         /* upstream's threshold */
#define NPAGE 3

static const u16 pad_x[6][2] = PAD_X;       /* codes 1..6: x0, x1 */
static const u8 sizes[NPAGE][3] = {{1, 2, 4}, {4, 8, 16}, {16, 32, 64}};
static const u32 spr[6] = SPR;              /* codes 1..6: sprite, style 0 */

struct bj_state {
    u8 held, swiped, code, prev, page, pad[3];
    u16 x0, last_x, last_y, pad2;
    u32 taps, swipes, jumps;
};
struct bj_state bj_st;                      /* zero at install */

typedef void (*handler_t)(u32);

static int pad_at(int x, int y)
{
    int i;
    if (y < ROW_Y0 || y > ROW_Y1)
        return 0;
    for (i = 0; i < 6; i++)
        if (x >= pad_x[i][0] && x <= pad_x[i][1])
            return i + 1;
    return 0;
}

static void set_page(int p)
{
    int i;
    bj_st.page = (u8)p;
    for (i = 0; i < 6; i++)                 /* code 1+2i, 2+2i = << >> of size i/2 */
        R32(BJ_TAB + 8 * (i + 1)) = sizes[p][i / 2];
    for (i = 0; i < 6; i++) {
        int k;
        for (k = 0; k < 3; k++) {
            const u32 *src = (const u32 *)(LBL + ((p * 6 + i) * 3 + k) * BAND_BYTES);
            volatile u32 *dst = (volatile u32 *)((spr[i] + k * STYLE_STRIDE + BAND_OFF) | 0xA0000000u);
            u32 n;
            for (n = 0; n < BAND_BYTES / 4; n++)
                dst[n] = src[n];
        }
    }
}

int bj_touch(int down, int x, int y)
{
    struct bj_state *s = &bj_st;
    if (!down) {
        s->prev = 0;
        if (s->held) {
            s->held = 0;
            if (!s->swiped && R32(MODEW) == MODE_PERFORM) {
                s->jumps++;
                ((handler_t)BJ_HANDLER)(s->code);
            }
        }
        return 0;                           /* stock sees an idle frame */
    }
    s->last_x = (u16)x;
    s->last_y = (u16)y;
    if (s->held) {
        int d = (int)s->x0 - x;             /* > 0 = moved left */
        if (R32(MODEW) != MODE_PERFORM) {   /* screen changed under us */
            s->held = 0;
            s->prev = 1;
            return 0;
        }
        if (!s->swiped && (d > SWIPE_PX || d < -SWIPE_PX)) {
            int p = s->page + (d > 0 ? 1 : -1);
            s->swiped = 1;
            s->swipes++;
            if (p >= 0 && p < NPAGE)
                set_page(p);
        }
        return 1;
    }
    if (s->prev)                            /* press began elsewhere: stock's */
        return 0;
    s->prev = 1;
    if (R32(MODEW) != MODE_PERFORM)
        return 0;
    int c = pad_at(x, y);
    if (!c)
        return 0;
    s->held = 1;
    s->swiped = 0;
    s->code = (u8)c;
    s->x0 = (u16)x;
    s->taps++;
    return 1;
}
