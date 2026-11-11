        .section .entry,"ax"
        .global _probe_head
        .align 2
_probe_head:
        .long   _probe_fread
