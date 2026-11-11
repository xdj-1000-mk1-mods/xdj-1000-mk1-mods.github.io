        .section .entry,"ax"
        .global _mnt_head
        .align 2
_mnt_head:
        .long   _mnt_hook
