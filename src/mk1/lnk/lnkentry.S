/* lnkentry.S -- colour-over-LINK module header: the hook entry (goes into the
 * media task's audio-open pool word, see lnk.c) */
        .section .entry,"ax"
        .global _lnk_head
        .align 2
_lnk_head:
        .long   _lnk_open
