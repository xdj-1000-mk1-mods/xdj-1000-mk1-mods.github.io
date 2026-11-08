/* ext2entry.S -- 3-BAND from .2EX: header + the .EXT-parse wrapper.
 * The wrapper keeps r15 untouched until the stock parse returns (stack args
 * pass through): pr and ctx go to a static save area (one ANLZ loader task). */
        .section .entry,"ax"
        .global _ext2_head
        .align 2
_ext2_head:
        .long   0x32545845              /* "EXT2" */
        .long   _ext2_parse
        .long   _ext2_st
        .long   1                       /* version */

        .section .text.ext2_parse,"ax"
        .global _ext2_parse
        .align 2
_ext2_parse:
        mov.l   .Lsv,r0
        sts     pr,r1
        mov.l   r1,@r0
        mov.l   r4,@(4,r0)
        mov.l   r15,@(8,r0)
        mov.l   .Lstock,r0
        jsr     @r0
        nop
        mov.l   r0,@-r15
        mov.l   .Lsv,r1
        mov.l   @(4,r1),r4
        mov.l   @(8,r1),r5
        mov.l   .Ladd,r0
        jsr     @r0
        nop
        mov.l   @r15+,r0
        mov.l   .Lsv,r1
        mov.l   @r1,r1
        lds     r1,pr
        rts
        nop
        .align 2
.Lsv:    .long   _ext2_save
.Lstock: .long   PARSE_STOCK
.Ladd:   .long   _ext2_add
