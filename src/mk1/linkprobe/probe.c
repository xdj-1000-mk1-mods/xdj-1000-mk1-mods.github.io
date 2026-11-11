/* probe.c -- TEST ONLY (qemu): can code inside the firmware's audio-read path
 * open and read another file? Sits on the direct read slot (models stems_io
 * direct_slot) like the stems mixer: every audio read passes through. When
 * armed (the test writes a UTF-16 path into probe_st.path and sets arm = 1)
 * it opens that path once, then on later reads tries to read 512 bytes,
 * up to 8 tries 10 calls apart, recording every return value. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef u32 (*fread_t)(void *, u32, u32, u32);
typedef u32 (*open_fn)(const u16 *, const char *, u32);
typedef u32 (*read_fn)(void *, u32, u32, u32, u32);
typedef void (*close_fn)(u32, u32);

struct probe_state {
    u32 magic, arm, calls, phase, fp, opened_at, tries, n[8], at[8], closed, busy_hits;
    u16 path[96];
    u8 data[512];
};
struct probe_state probe_st = { 0x42525250u };       /* "PRRB" */
static u32 busy;

u32 probe_fread(void *buf, u32 size, u32 count, u32 fp)
{
    u32 got = ((fread_t)STOCK_FREAD)(buf, size, count, fp);
    if (busy) { probe_st.busy_hits++; return got; }
    probe_st.calls++;
    if (!probe_st.arm) return got;
    busy = 1;
    if (probe_st.phase == 0) {
        probe_st.fp = ((open_fn)FOPEN_W)(probe_st.path, "r", 0);
        probe_st.opened_at = probe_st.calls;
        probe_st.phase = probe_st.fp ? 1 : 9;
    } else if (probe_st.phase == 1 && probe_st.calls >= probe_st.opened_at + 10 * (probe_st.tries + 1)) {
        u32 k = probe_st.tries++;
        probe_st.n[k] = ((read_fn)FREAD_C)(probe_st.data, 1, 512, probe_st.fp, 0);
        probe_st.at[k] = probe_st.calls;
        if ((probe_st.n[k] && probe_st.n[k] <= 512) || probe_st.tries == 8) {
            ((close_fn)FCLOSE_C)(probe_st.fp, 0);
            probe_st.closed = 1;
            probe_st.phase = 2;
        }
    }
    busy = 0;
    return got;
}
