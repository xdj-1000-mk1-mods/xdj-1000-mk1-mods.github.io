/* ldrentry.S -- stick loader header at the module base: magic, the hook entry
 * (goes into the mount check's path_build pool word, see ldr.c), the state. */
        .section .entry,"ax"
        .global _ldr_head
        .align 2
_ldr_head:
        .long   0x4C314B4D              /* "MK1L" */
        .long   _ldr_path_build
        .long   STATE
#ifdef LINK_SET_STOCK
        .long   2                       /* loader version: X (own stick + linked stick) */
        .long   _ldr_link_mount         /* goes into the LINK code's set-drive-type pool word */
#else
        .long   1                       /* loader version */
#endif
