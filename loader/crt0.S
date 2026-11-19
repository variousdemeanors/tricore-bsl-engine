/*
 * crt0.S -- GammaFlash TC1767 CANLoader startup (TriCore, HighTec GCC asm).
 *
 * Authored for GammaFlash from the HighTec-shipped TriCore crt0 pattern (the
 * toolchain ships its own under lib/; this is the minimal subset we need).
 * Reference for structure only: fastboatster/TC1796_CAN_bootloader (a related,
 * unlicensed AUDO-NG CAN bootloader project) -- no code copied from it.
 *
 * Does: reset the clock to Prescaler Mode, disable watchdog, clear ENDINIT, set
 * up user/interrupt stacks, build the CSA free list, install the trap vector
 * table, set PSW.CDE, then jump to main(). No .data copy is needed: the image
 * is loaded straight into SPRAM by the BootROM; globals in DSPR are zeroed below.
 */

	.section ".startup_code", "awx", @progbits
	.global _start
	.type _start,@function
_start:
	.code32

	/* --- reset clock to Prescaler Mode (MUST be first) --- */
	/* After the BootROM jumps here the clock is in PLL-freerunning mode, a
	 * different frequency than the one the CAN baud was auto-calibrated for, so
	 * the inherited bit timing is the WRONG baud and TX is unintelligible until
	 * this runs. AP32132 CANLoader: the loader must reset the clock to Prescaler
	 * Mode first thing. SCU prescaler-mode byte writes (AP32132):
	 * 0xF000051E<-0x00, 0xF0000518<-0x01. */
	lea     %a15, 0xF000051E
	mov     %d15, 0
	st.b    [%a15], %d15
	lea     %a15, 0xF0000518
	mov     %d15, 1
	st.b    [%a15], %d15

	/* --- disable the watchdog + set ENDINIT --- */
	/* TC1767 sequence, transcribed from the toolchain's own crt0-tc1x.S
	 * _disable_wdt (symbols $wdtcon0=0xF00005F0, $wdtcon1=0xF00005F4; masks
	 * 0xFFFFFF03 / 0xFFFFFFF0). These are the standard TC1767 WDTCON0/1
	 * addresses -- a related AUDO family's 0xF0000020/24 pair does NOT apply
	 * to TC1767 and leaves the watchdog enabled (chip resets mid-loader). */
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

	/* --- zero globals in DSPR [__DRAM_BEGIN, __DRAM_END) (not part of the upload) --- */
	movh.a  %a2, hi:__DRAM_BEGIN
	lea     %a2, [%a2]lo:__DRAM_BEGIN
	movh    %d1, hi:__DRAM_BEGIN
	addi    %d1, %d1, lo:__DRAM_BEGIN
	movh    %d2, hi:__DRAM_END
	addi    %d2, %d2, lo:__DRAM_END
	mov     %d0, 0
1:	jge.u   %d1, %d2, 2f
	st.w    [%a2+]4, %d0
	add     %d1, %d1, 4
	j       1b
2:
	/* --- install the trap vector table (BTV) ---
	 * Without this, a trap inherits the BootROM's vectors and never returns to
	 * our command loop -> the core wedges until a power cycle. The only trap the
	 * loader can realistically take is a flash-command bus error (class 4, DAE);
	 * every class here warm-restarts via _start (see __TRAP_TAB below). */
	movh    %d0, hi:__TRAP_TAB
	addi    %d0, %d0, lo:__TRAP_TAB
	mtcr    $btv, %d0
	isync

	j       main
	.size _start, .-_start

	/* ================= trap vector table =================
	 * TriCore trap vectors are spaced 0x20 bytes apart, one per class (0..7);
	 * BTV points here. A flash erase/program that hits an invalid command region
	 * raises a bus-error / DAE trap (class 4). Rather than attempt to resume the
	 * faulting mid-flash context, every class jumps to _start: a clean warm
	 * restart that rebuilds the CSA free list and re-enters main()'s command
	 * loop. Net effect on the host: a failed op becomes a recoverable ack-timeout
	 * (the loader is answering again immediately after), never a wedge needing a
	 * power cycle. Table base and each slot are 32-byte aligned. */
	.balign 32
	.global __TRAP_TAB
	.type __TRAP_TAB,@function
__TRAP_TAB:
	.rept 8
	j       _start
	.balign 32
	.endr
	.size __TRAP_TAB, .-__TRAP_TAB
