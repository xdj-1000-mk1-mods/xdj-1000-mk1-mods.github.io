/* ldrentry.S -- stick loader header at the module base: magic, the hook entry
 * (goes into the mount check's path_build pool word, see ldr.c), the state. */
        .section .entry,"ax"
        .global _ldr_head
        .align 2
_ldr_head:
        .long   0x4C314B4D              /* "MK1L" */
        .long   _ldr_path_build
        .long   STATE
        .long   1                       /* loader version */
