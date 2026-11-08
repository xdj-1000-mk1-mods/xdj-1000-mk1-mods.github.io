/* stemsuientry.S -- STEMS UI hooks. Header at the module base: magic, the
 * two entries. Both chain to what the slot held before (set by the
 * installer): the display-flush hook always; the touch hook (hit-tester
 * slot) unless stemsui_on_touch() took the touch (then return 0, like a
 * hit-tester that found nothing). */
        .section .entry,"ax"
        .global _stemsui_head
        .align 2
_stemsui_head:
        .long   0x49555453              /* "STUI" */
        .long   _stemsui_flush
        .long   _stemsui_touch

        .section .text.stemsui_entries,"ax"
        .global _stemsui_flush, _stemsui_touch
        .align 2
_stemsui_flush:
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
_stemsui_touch:
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
.Lflush: .long  _stemsui_on_flush
.Ltouch: .long  _stemsui_on_touch
.Lfprev: .long  _stemsui_fprev
.Ltprev: .long  _stemsui_tprev

        .section .data
        .global _stemsui_fprev, _stemsui_tprev
        .align 2
_stemsui_fprev: .long FLUSH_STOCK          /* installer: the live flush slot value */
_stemsui_tprev: .long HIT_STOCK            /* installer: the live touch slot value */
