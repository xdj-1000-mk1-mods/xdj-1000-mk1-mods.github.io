/* mount.c -- TEST ONLY (qemu): on the LINK code's call of the firmware's
 * set-drive-type routine (models link_drive: pool 0x08cfdc54 -> 0x08d88fe4,
 * args drive letter, type, remote drive, peer IP), after the stock call:
 * mode 1 = open "<drive>:/<name>" right here (the task that mounts the linked
 * drive), read 512 bytes, close; mode 0 = only record the call. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef u32 (*set_fn)(int, int, int, u32);
typedef u32 (*open_fn)(const u16 *, const char *, u32);
typedef u32 (*read_fn)(void *, u32, u32, u32, u32);
typedef void (*close_fn)(u32, u32);

struct mnt_state {
    u32 magic, mode, calls, drive, type, rdrive, ip, stage, fp, n, done;
    char name[64];
    u8 data[512];
};
struct mnt_state mnt_st = { 0x544E4D4Cu, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                            "PIONEER/rekordbox/export.pdb" };

u32 mnt_hook(int drive, int type, int rdrive, u32 ip)
{
    u32 r = ((set_fn)STOCK_SET)(drive, type, rdrive, ip);
    mnt_st.calls++;
    mnt_st.drive = (u32)drive; mnt_st.type = (u32)type; mnt_st.rdrive = (u32)rdrive; mnt_st.ip = ip;
    if (mnt_st.mode != 1 || type != 5 || mnt_st.done) return r;
    u16 w[80];
    u32 k = 0;
    w[k++] = (u16)(drive & 0xFF); w[k++] = ':'; w[k++] = '/';
    for (u32 i = 0; mnt_st.name[i] && k < 78; i++) w[k++] = (u8)mnt_st.name[i];
    w[k] = 0;
    mnt_st.stage = 1;
    mnt_st.fp = ((open_fn)FOPEN_W)(w, "r", 0);
    mnt_st.stage = 2;
    if (mnt_st.fp) {
        mnt_st.n = ((read_fn)FREAD_C)(mnt_st.data, 1, 512, mnt_st.fp, 0);
        mnt_st.stage = 3;
        ((close_fn)FCLOSE_C)(mnt_st.fp, 0);
    }
    mnt_st.stage = 4;
    mnt_st.done = 1;
    return r;
}
