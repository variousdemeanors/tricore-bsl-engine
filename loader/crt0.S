/*
 * crt0.S -- GammaFlash TC1767 CANLoader startup (TriCore, HighTec GCC asm).
 *
 * Authored for GammaFlash from the HighTec-shipped TriCore crt0 pattern (the
 * toolchain ships its own under lib/; this is the minimal subset we need).
 * Reference for structure only: fastboatster/TC1796_CAN_bootloader crt0.S
 * (commit 80e785b). The TC1796-specific SBRAM-unlock poke at 0xF801E0 is
 * DELIBERATELY OMITTED -- it is not applicable to TC1767 SPRAM.
 *
 * Does: disable watchdog, clear ENDINIT, set up user/interrupt stacks, build
 * the CSA free list, set PSW.CDE, then jump to main(). No .data copy / .bss
 * clear is needed: the image is loaded straight into SPRAM by the BootROM and
 * .bss lives in that same already-zeroable window (we zero it below to be safe).
 *
 * WDTCON0 = 0xF0000020, WDTCON1 = 0xF0000024: CONFIRMED against fastboatster/TC1796
 * reg176x.h (WDT_CON0/WDT_CON1), TC1796 being the same AUDO-NG family as TC1767.
 * TODO(bench): final-confirm vs the TC1767 UM (SCU chapter) before trusting on HW.
 */

	.section ".startup_code", "awx", @progbits
	.global _start
	.type _start,@function
_start:
	.code32

	/* --- reset clock to Prescaler Mode (MUST be first) --- */
	/* After the BootROM jumps here the clock is in PLL-freerunning mode, a
	 * different frequency than the one the CAN baud was auto-calibrated for, so
	 * the inherited bit timing is the WRONG baud and our TX is unintelligible
	 * (bench 2026-11-12: loader uploaded+jumped but silent). AP32132 §3.x: the
	 * CANLoader must reset the clock to Prescaler Mode. SCU prescaler-mode byte
	 * writes (AP32132): 0xF000051E<-0x00, 0xF0000518<-0x01. */
	lea     %a15, 0xF000051E
	mov     %d15, 0
	st.b    [%a15], %d15
	lea     %a15, 0xF0000518
	mov     %d15, 1
	st.b    [%a15], %d15

	/* --- disable the watchdog + set ENDINIT --- */
	/* AUTHORITATIVE TC1767 sequence, transcribed from the toolchain's own
	 * crt0-tc1x.S _disable_wdt (symbols $wdtcon0=0xF00005F0, $wdtcon1=0xF00005F4;
	 * masks 0xFFFFFF03 / 0xFFFFFFF0). The earlier 0xF0000020/24 addresses were
	 * WRONG for TC1767 -> WDT never disabled -> chip reset mid-loader (bench
	 * 2026-11-12). These are the standard TC1767 WDTCON0/1 addresses. */
	movh    %d2, 0
	addi    %d2, %d2, -253            /* WDTMASK  0xFFFFFF03 */
	movh    %d5, 0
	addi    %d5, %d5, -16             /* WDTMASK2 0xFFFFFFF0 */
	mov     %d6, 8
	st.w    0xF00005F4, %d6           /* WDTCON1 = 0x08 (disable request) */
	ld.w    %d0, 0xF00005F0           /* WDTCON0 (current password) */
	ld.w    %d1, 0xF00005F4           /* WDTCON1 */
	and     %d3, %d2, %d0
	or      %d3, %d3, 240
	and     %d4, %d1, 12
	or      %d3, %d4
	xor     %d3, %d3, 2
	st.w    0xF00005F0, %d3           /* WDTCON0: password write, clear ENDINIT */
	and     %d3, %d5
	or      %d3, %d3, 3
	st.w    0xF00005F0, %d3           /* WDTCON0: set ENDINIT -> WDT disabled */
	ld.w    %d0, 0xF00005F0           /* readback/sync */

	/* --- user + interrupt stack pointers --- */
	movh.a  %sp, hi:__USTACK
	lea     %sp, [%sp]lo:__USTACK
	movh    %d0, hi:__ISTACK
	addi    %d0, %d0, lo:__ISTACK
	mtcr    $isp, %d0
	isync

	/* --- call-depth counter: reset, set CDE --- */
	mfcr    %d0, $psw
	andn    %d0, %d0, 0x7F
	or      %d0, %d0, 0x80
	mtcr    $psw, %d0
	isync

	/* --- build the CSA free list between __CSA_BEGIN and __CSA_END --- */
__init_csa:
	movh    %d0, 0
	mtcr    $pcxi, %d0
	isync
	movh    %d0, hi:__CSA_BEGIN
	addi    %d0, %d0, lo:__CSA_BEGIN
	addi    %d0, %d0, 63
	andn    %d0, %d0, 63
	movh    %d2, hi:__CSA_END
	addi    %d2, %d2, lo:__CSA_END
	andn    %d2, %d2, 63
	sub     %d2, %d2, %d0
	sh      %d2, %d2, -6              /* %d2 = number of CSAs */
	mov.a   %a3, %d0
	extr.u  %d0, %d0, 28, 4
	sh      %d0, %d0, 16
	lea     %a4, 0
	st.a    [%a3], %a4
	mov.aa  %a4, %a3
	lea     %a3, [%a3]64
	mov.d   %d1, %a3
	extr.u  %d1, %d1, 6, 16
	or      %d1, %d1, %d0
	mtcr    $lcx, %d1
	add     %d2, %d2, -2
	mov.a   %a5, %d2
csa_loop:
	mov.d   %d1, %a4
	extr.u  %d1, %d1, 6, 16
	or      %d1, %d1, %d0
	st.w    [%a3], %d1
	mov.aa  %a4, %a3
	lea     %a3, [%a3]64
	loop    %a5, csa_loop

	mov.d   %d1, %a4
	extr.u  %d1, %d1, 6, 16
	or      %d1, %d1, %d0
	mtcr    $fcx, %d1
	isync

	j       main
	.size _start, .-_start
