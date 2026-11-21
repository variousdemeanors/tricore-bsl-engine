/*
 * loader.ld -- GNU ld script for the TC1767 CANLoader / ASCLoader.
 *
 * Memory split (matches Infineon's official AP32132 CANLoader and is
 * bench-proven on real TC1767 silicon):
 *
 *   SPRAM / PSPR @ 0xD4000000 (0x1400 window) -- CODE + RODATA ONLY. This is
 *       the region the BootROM CAN/ASC BSL copies the uploaded image into and
 *       jumps to, so it is the only thing that must stay inside 0x1400 bytes.
 *   DSPR        @ 0xD0000000 -- CSA (context-save area), .data, .bss, and the
 *       stacks. None of this is part of the uploaded image; crt0.S builds the
 *       CSA free list and zeroes [__DRAM_BEGIN, __DRAM_END) at startup.
 *
 * Why the split: with CSA/stack/globals in PSPR, any reply nested two calls
 * deep (e.g. ack-then-error) hangs the loader while a one-deep keep-alive still
 * works -- the failure mode that identified this. AP32132's CANLoader.ld keeps
 * only code in PSPR and puts the CSA + stacks + data in DSPR; this mirrors it.
 *
 * The ASSERT below is the hard gate: if code+rodata would spill past the 0x1400
 * SPRAM window the link FAILS rather than producing an image the BootROM would
 * silently truncate. (DSPR has ample room and is not uploaded, so only SPRAM is
 * gated.) The Makefile's check-size target is the same gate on the final .bin.
 */

OUTPUT_FORMAT("elf32-tricore")
OUTPUT_ARCH(tricore)
ENTRY(_start)

MEMORY
{
    SPRAM (rx)  : ORIGIN = 0xD4000000, LENGTH = 0x1400   /* PSPR: code + rodata ONLY (uploaded) */
    DSPR  (rw)  : ORIGIN = 0xD0000000, LENGTH = 0x4000   /* DSPR: CSA, data, stacks (NOT uploaded) */
}

/* Stack + CSA sizes. A read/erase/program loop needs little; tune on bench if a
 * trap (FCU/CSU) shows CSA exhaustion. These live in DSPR, outside the 0x1400
 * SPRAM gate, so growing them costs no SPRAM budget. */
__STACK_SIZE  = 0x400;   /* 1 KB user stack */
__ISTACK_SIZE = 0x100;   /* interrupt stack (no IRQs enabled) */
__CSA_SIZE    = 0x800;   /* 32 x 64-B context save areas */

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

    __LOADER_END = .;        /* end of the uploaded SPRAM image (gated below) */

    /* ---- DSPR scratch: none of this is in the uploaded image ---- */
    .csa (NOLOAD) : {
        . = ALIGN(64);
        __CSA_BEGIN = .;
        . += __CSA_SIZE;
        __CSA_END = .;
    } > DSPR

    .dram (NOLOAD) : {
        . = ALIGN(8);
        __DRAM_BEGIN = .;        /* crt0 zeroes [__DRAM_BEGIN, __DRAM_END) */
        *(.data .data.*)
        *(.bss .bss.*)
        *(COMMON)
        *(.g_*)                  /* tricore-gcc -fdata-sections names globals .g_<name> */
        . = ALIGN(8);
        __DRAM_END = .;
        . += __ISTACK_SIZE;
        __ISTACK = .;            /* interrupt stack top (top-down) */
        . = ALIGN(8);
        . += __STACK_SIZE;
        __USTACK = .;            /* user stack top (top-down) */
    } > DSPR

    /DISCARD/ : { *(.comment) *(.note.*) *(.eh_frame) }
}

ASSERT(__LOADER_END <= (ORIGIN(SPRAM) + LENGTH(SPRAM)),
       "CANLoader image exceeds the 0x1400 SPRAM loader window");
