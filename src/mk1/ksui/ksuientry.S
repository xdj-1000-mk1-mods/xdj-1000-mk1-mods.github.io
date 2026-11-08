/* ksuientry.S -- KEY SHIFT UI hooks. Header at the module base: magic, the
 * two entries. Both chain to what the slot held before (set by the
 * installer): the display-flush hook always; the touch hook (hit-tester
 * slot) unless ksui_on_touch() took the touch (then return 0, like a
 * hit-tester that found nothing). */
        .section .entry,"ax"
        .global _ksui_head
        .align 2
_ksui_head:
        .long   0x4955534B              /* "KSUI" */
        .long   _ksui_flush
        .long   _ksui_touch

        .section .text.ksui_entries,"ax"
        .global _ksui_flush, _ksui_touch
        .align 2
_ksui_flush:
        sts.l   pr,@-r15
        mov.l   r4,@-r15
        mov.l   r5,@-r15
        mov.l   r6,@-r15
        mov.l   r7,@-r15
        mov.l   .Lflush,r0
        jsr     @r0
        nop
        mov.l   @r15+,r7
        mov.l   @r15+,r6
        mov.l   @r15+,r5
        mov.l   @r15+,r4
        lds.l   @r15+,pr
        mov.l   .Lfprev,r0
        mov.l   @r0,r0
        jmp     @r0
        nop
_ksui_touch:
        sts.l   pr,@-r15
        mov.l   r4,@-r15
        mov.l   r5,@-r15
        mov.l   r6,@-r15
        mov.l   r7,@-r15
        mov.l   .Ltouch,r0
        jsr     @r0
        nop
        mov.l   @r15+,r7
        mov.l   @r15+,r6
        mov.l   @r15+,r5
        mov.l   @r15+,r4
        lds.l   @r15+,pr
        tst     r0,r0
        bf      .Lown
        mov.l   .Ltprev,r0
        mov.l   @r0,r0
        jmp     @r0
        nop
.Lown:
        rts
        mov     #0,r0
        .align 2
.Lflush: .long  _ksui_on_flush
.Ltouch: .long  _ksui_on_touch
.Lfprev: .long  _ksui_fprev
.Ltprev: .long  _ksui_tprev

        .section .data
        .global _ksui_fprev, _ksui_tprev
        .align 2
_ksui_fprev: .long FLUSH_STOCK          /* installer: the live flush slot value */
_ksui_tprev: .long HIT_STOCK            /* installer: the live touch slot value */
