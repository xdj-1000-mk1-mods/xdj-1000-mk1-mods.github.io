/* aopen.c -- TEST ONLY (qemu): on the media task's open of the track's audio
 * file (pool 0x08d8b86c -> fopen_w; models link_drive), after the stock open
 * of a "D:/..." path: open "D:/<name>" in the same task and read 512 bytes,
 * first with the caller's descriptor, then (if that read gives nothing) with
 * the default one. Records everything; mode 0 = only record the path. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef u32 (*open_fn)(const u16 *, const char *, u32);
typedef u32 (*read_fn)(void *, u32, u32, u32, u32);
typedef void (*close_fn)(u32, u32);

struct ao_state {
    u32 magic, mode, calls, dcalls, stage, fp, n1, fp2, n2, done, desc;
    char name[64];
    u16 last[96];
    u8 data[512];
};
struct ao_state ao_st = { 0x4E504F41u, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "PIONEER/rekordbox/export.pdb" };

u32 ao_hook(const u16 *path, const char *mode, u32 desc)
{
    u32 fp = ((open_fn)FOPEN_W)(path, mode, desc);
    ao_st.calls++;
    for (u32 i = 0; i < 95; i++) { ao_st.last[i] = path[i]; if (!path[i]) break; }
    if (path[0] != 'D' || path[1] != ':') return fp;
    ao_st.dcalls++;
    ao_st.desc = desc;
    if (ao_st.mode != 1 || ao_st.done) return fp;
    u16 w[80];
    u32 k = 0;
    w[k++] = 'D'; w[k++] = ':'; w[k++] = '/';
    for (u32 i = 0; ao_st.name[i] && k < 78; i++) w[k++] = (u8)ao_st.name[i];
    w[k] = 0;
    ao_st.stage = 1;
    ao_st.fp = ((open_fn)FOPEN_W)(w, "r", desc);
    ao_st.stage = 2;
    if (ao_st.fp) {
        ao_st.n1 = ((read_fn)FREAD_C)(ao_st.data, 1, 512, ao_st.fp, desc);
        ao_st.stage = 3;
        ((close_fn)FCLOSE_C)(ao_st.fp, desc);
    }
    if (!ao_st.fp || ao_st.n1 != 512) {
        ao_st.stage = 4;
        ao_st.fp2 = ((open_fn)FOPEN_W)(w, "r", 0);
        if (ao_st.fp2) {
            ao_st.n2 = ((read_fn)FREAD_C)(ao_st.data, 1, 512, ao_st.fp2, 0);
            ((close_fn)FCLOSE_C)(ao_st.fp2, 0);
        }
    }
    ao_st.stage = 9;
    ao_st.done = 1;
    return fp;
}
