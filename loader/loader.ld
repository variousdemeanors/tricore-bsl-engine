/*
 * loader.ld -- GNU ld script for the GammaFlash TC1767 read-only CANLoader.
 *
 * The BootROM CAN BSL copies our image to SPRAM 0xD4000000 (640 x 8-byte data
 * frames, 5120 B max) and jumps to it. EVERYTHING -- code, rodata, data, bss,
 * stack and the Context Save Area -- must live inside the first 0x1400 bytes of
 * SPRAM, because the user/exec region begins at 0xD4001400 (spec: SPRAM layout).
 *
 * The ASSERT at the end is the hard gate: if the image would spill past 0x1400
 * the link FAILS rather than producing a loader the BootROM silently truncates.
 *
 * TODO(bench): confirm the SPRAM base/size for TC1767 (0xD4000000, 24 KB) against
 * the TC1767 User Manual. It matches AP32132 for AUDO-F; verify on the part.
 */

OUTPUT_FORMAT("elf32-tricore")
OUTPUT_ARCH(tricore)
ENTRY(_start)

MEMORY
{
    SPRAM (rwx) : ORIGIN = 0xD4000000, LENGTH = 0x1400   /* 5120 B loader window */
}

/* Stack + CSA sizes. Keep small: a read loop needs little. Tune on bench if a
 * trap (FCU/CSU) shows CSA exhaustion. */
__STACK_SIZE = 0x200;    /* 512 B user stack */
__ISTACK_SIZE = 0x80;    /* 128 B interrupt stack (unused: no IRQs enabled) */
__CSA_SIZE = 0x200;      /* 512 B = 8 x 64-B context save areas */

SECTIONS
{
    . = ORIGIN(SPRAM);

    .startup_code : { KEEP(*(.startup_code)) } > SPRAM

    .text : {
        *(.text .text.*)
        *(.gnu.linkonce.t.*)
    } > SPRAM

    .rodata : {
        *(.rodata .rodata.*)
        *(.gnu.linkonce.r.*)
    } > SPRAM

    .data : {
        *(.data .data.*)
    } > SPRAM

    .bss (NOLOAD) : {
        *(.bss .bss.*)
        *(COMMON)
    } > SPRAM

    . = ALIGN(8);

    /* Context Save Area (CSA) -- crt0 links these as a free list. */
    . = ALIGN(64);
    __CSA_BEGIN = .;
    . += __CSA_SIZE;
    . = ALIGN(64);
    __CSA_END = .;

    /* Interrupt stack (top-down) */
    . = ALIGN(8);
    . += __ISTACK_SIZE;
    __ISTACK = .;

    /* User stack (top-down) */
    . = ALIGN(8);
    . += __STACK_SIZE;
    __USTACK = .;

    __LOADER_END = .;

    /DISCARD/ : { *(.comment) *(.note.*) *(.eh_frame) }
}

ASSERT(__LOADER_END <= (ORIGIN(SPRAM) + LENGTH(SPRAM)),
       "CANLoader image exceeds the 0x1400 SPRAM loader window");
