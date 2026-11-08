/* ut_mk1.c -- WAVEFORM COLOR row in the MK1's own UTILITY list.
 *
 * Port of upstream tools/utility/ut.c: its WAVEFORM COLOR row (mod:
 * mk1/rgb_mk1.py) plus PHASE METER OFF/ON (pm_mode of mk1/phasemeter_mk1.py;
 * upstream switched the meter through MODS / MY SETTINGS, which MK1 lacks).
 * Same record layout (52 bytes, see ut.c), same stock callbacks, same
 * draw/commit logic. PHASE METER shows NOT INSTALLED (one value, no commit)
 * unless the meter's module is in RAM (PM_SIG = pm_hook's address, held by
 * its entry stub's literal at PM_BASE). Every address comes from mk1/models/<model>.json through
 * utility_mk1.py (-D...), none is written here.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define R8(a)  (*(volatile u8 *)(a))

#if !defined(NSTOCK) || !defined(MODEB) || !defined(CB_NOP) || !defined(CB_DRAW) \
    || !defined(CB_BEGIN) || !defined(CB_SEL) || !defined(CB_Q0) || !defined(CB_END) \
    || !defined(PM_BASE) || !defined(PM_SIG) || !defined(PM_MODE)
#error address defines missing (mk1/utility_mk1.py)
#endif

#define R32(a) (*(volatile u32 *)(a))
#define NOURS 2

enum { K_WAVE, K_PM };

static const u16 L_WAVE[] = u"WAVEFORM COLOR";
static const u16 L_PM[] = u"PHASE METER";
static const u16 S_BLUE[] = u"BLUE", S_RGB[] = u"RGB", S_3B[] = u"3-BAND";
static const u16 S_OFF[] = u"OFF", S_ON[] = u"ON", S_NONE[] = u"NOT INSTALLED";
static const u16 *const V_WAVE[] = {S_BLUE, S_RGB, S_3B};
static const u16 *const V_PM[] = {S_OFF, S_ON};
static const u16 *const V_NONE[] = {S_NONE};

int ut_draw(u32 *r, u32 ui);
int ut_commit(u32 *r);

#define REC(lbl, vals, n) {(u32)(lbl), (u32)(vals), (n), 0, 0xFFFFFFFFu, 1, \
    CB_NOP, (u32)ut_draw, CB_BEGIN, CB_SEL, (u32)ut_commit, CB_Q0, CB_END}

u32 ut_tab[NSTOCK + NOURS][13] = {
    [NSTOCK + K_WAVE] = REC(L_WAVE, V_WAVE, 3),
    [NSTOCK + K_PM]   = REC(L_PM, V_NONE, 1),
};
u32 ut_draws, ut_commits;                 /* diagnostics */

static int kind_of(u32 *r)
{
    return (int)((r - ut_tab[NSTOCK]) / 13);
}

static int pm_installed(void)
{
    return R32(PM_BASE) == PM_SIG;
}

static u32 current(int k, u32 *r)
{
    if (k == K_WAVE) {
        u32 v = R8(MODEB);
        return v < 3 ? v : 0;
    }
    if (!pm_installed()) {                   /* one value, nothing to edit */
        r[1] = (u32)V_NONE; r[2] = 1;
        return 0;
    }
    r[1] = (u32)V_PM; r[2] = 2;
    return R8(PM_MODE) == 1 ? 1 : 0;
}

typedef int (*draw_t)(u32 *, u32);

int ut_draw(u32 *r, u32 ui)
{
    int ret;
    ut_draws++;
    if (r[4] != 0xFFFFFFFFu)                 /* editing: show the choice */
        return ((draw_t)CB_DRAW)(r, ui);
    r[3] = current(kind_of(r), r);
    r[4] = r[3];                             /* stock draw skips its own */
    ret = ((draw_t)CB_DRAW)(r, ui);          /* value fetch (row 0's draw) */
    r[4] = 0xFFFFFFFFu;
    return ret;
}

int ut_commit(u32 *r)
{
    u32 v = r[4];
    if (v >= (r[2] & 0xFFFF) || v == r[3])
        return 0;
    if (kind_of(r) == K_PM) {
        if (!pm_installed())
            return 0;
        ut_commits++;
        R8(PM_MODE) = (u8)v;                 /* 0 = stock meter, 1 = Type 1 */
        r[3] = v;
        return 1;
    }
    ut_commits++;
    R8(MODEB) = (u8)v;
    r[3] = v;
    return 1;
}
