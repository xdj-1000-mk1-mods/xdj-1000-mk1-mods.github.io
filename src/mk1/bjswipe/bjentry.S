/* bjentry.S -- the touch hook (the hit-tester slot points at _bj_entry).
 * Calls bj_touch(down, x, y); r0 != 0 = we own this touch (return 0, like
 * a hit-tester that found nothing), else tail-jump to the stock hit-tester
 * with r4-r7 untouched. */
        .section .entry,"ax"
        .global _bj_head
        .global _bj_entry
        .align 2
_bj_head:
        .long   0x5753424A              /* "JBSW" */
        .long   _bj_entry

        .section .text.bj_entry,"ax"
        .align 2
_bj_entry:
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
        mov.l   .Lstock,r0
        jmp     @r0
        nop
.Lown:
        rts
        mov     #0,r0
        .align 2
.Ltouch:
        .long   _bj_touch
.Lstock:
        .long   STOCK_HIT
