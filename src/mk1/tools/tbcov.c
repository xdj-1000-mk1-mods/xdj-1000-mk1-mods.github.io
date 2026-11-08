/*
 * tbcov: QEMU TCG plugin -- which translation blocks ran, and how often.
 *
 * Every executed TB start address is counted; at exit the plugin writes
 * "<pc hex> <count> <insns> <first>" lines to out=<file> (default
 * tbcov.txt), <first> being the global TB-execution number at which that
 * block first ran (so a window's new blocks can be put in execution order).
 * Run one QEMU per trace window (restored from the same snapshot), so a
 * window's set minus the baseline's is what the action alone executed.
 *
 *   -plugin ./libtbcov.dylib,out=/path/trace.txt
 *
 * Build (macOS):
 *   cc -O2 -shared -fPIC -undefined dynamic_lookup \
 *      -I<qemu-src>/include/plugins $(pkg-config --cflags glib-2.0) \
 *      (QEMU 11.x, plugin API 7: header in include/plugins, the translate
 *      callback is (tb, userdata), the atexit callback (userdata); on 9.1 /
 *      API 3 they were include/qemu, (id, tb) and (id, userdata))
 *      -o libtbcov.dylib tbcov.c
 */
#include <glib.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include <qemu-plugin.h>

QEMU_PLUGIN_EXPORT int qemu_plugin_version = QEMU_PLUGIN_VERSION;

typedef struct {
    uint64_t pc;
    uint64_t count;
    uint64_t first;
    uint32_t insns;
} Entry;

static GHashTable *blocks;     /* pc -> Entry*, one vCPU so no lock */
static char *out_path;
static uint64_t seq;           /* global TB executions so far */

static void on_exec(unsigned int vcpu, void *udata)
{
    Entry *e = udata;
    if (!e->count++) {
        e->first = seq;
    }
    seq++;
}

static void on_trans(struct qemu_plugin_tb *tb, void *ud)
{
    uint64_t pc = qemu_plugin_tb_vaddr(tb);
    Entry *e = g_hash_table_lookup(blocks, &pc);
    if (!e) {
        e = g_new0(Entry, 1);
        e->pc = pc;
        e->insns = qemu_plugin_tb_n_insns(tb);
        g_hash_table_insert(blocks, &e->pc, e);
    }
    qemu_plugin_register_vcpu_tb_exec_cb(tb, on_exec, QEMU_PLUGIN_CB_NO_REGS, e);
}

static void on_exit(void *p)
{
    FILE *f = fopen(out_path, "w");
    GHashTableIter it;
    gpointer k, v;
    if (!f) {
        return;
    }
    g_hash_table_iter_init(&it, blocks);
    while (g_hash_table_iter_next(&it, &k, &v)) {
        Entry *e = v;
        if (e->count) {
            fprintf(f, "%08" PRIx64 " %" PRIu64 " %u %" PRIu64 "\n",
                    e->pc, e->count, e->insns, e->first);
        }
    }
    fclose(f);
}

QEMU_PLUGIN_EXPORT int qemu_plugin_install(qemu_plugin_id_t id,
                                           const qemu_info_t *info,
                                           int argc, char **argv)
{
    out_path = g_strdup("tbcov.txt");
    for (int i = 0; i < argc; i++) {
        if (g_str_has_prefix(argv[i], "out=")) {
            g_free(out_path);
            out_path = g_strdup(argv[i] + 4);
        }
    }
    blocks = g_hash_table_new(g_int64_hash, g_int64_equal);
    qemu_plugin_register_vcpu_tb_trans_cb(id, on_trans, NULL);
    qemu_plugin_register_atexit_cb(id, on_exit, NULL);
    return 0;
}
