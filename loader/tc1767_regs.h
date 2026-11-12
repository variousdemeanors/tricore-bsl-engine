/*
 * tc1767_regs.h -- isolated, hardware-specific register definitions for the
 * GammaFlash TC1767 CANLoader. THIS is the only file whose constants are not
 * verified in simulation; every address below is marked TODO(bench) and must be
 * confirmed against the TC1767 User Manual before the loader is trusted on a
 * live part. The BSL logic in main.c is hardware-independent and sim-tested.
 *
 * MultiCAN handoff assumption (AP32132 CAN BSL):
 *   The BootROM's CAN bootstrap loader configures the CAN node (bit timing,
 *   auto-baud from the host init frame) and two message objects -- MO0 for
 *   receive (host -> loader) and MO1 for transmit (loader -> host) -- and jumps
 *   to our image with that configuration live. We therefore DO NOT re-init the
 *   node or bit timing; we only poll/drive NEWDAT and TXRQ on MO0/MO1. This
 *   mirrors fastboatster/TC1796_CAN_bootloader, which likewise never re-inits.
 *   TODO(bench): confirm MO0=rx, MO1=tx is what the TC1767 BootROM leaves set.
 */
#ifndef GAMMAFLASH_TC1767_REGS_H
#define GAMMAFLASH_TC1767_REGS_H

typedef unsigned char      u8;
typedef unsigned short     u16;
typedef unsigned int       u32;

#define REG32(addr)  (*(volatile u32 *)(addr))

/* ---- MultiCAN message-object register space ----------------------------
 * Standard TriCore MultiCAN per-message-object layout, 0x20 bytes each:
 *   +0x00 MOFCR   +0x04 MOFGPR  +0x08 MOIPR   +0x0C MOAMR
 *   +0x10 MODATAL +0x14 MODATAH +0x18 MOAR    +0x1C MOCTR (write) / MOSTAT (read)
 *
 * CAN_MSGOBJ_BASE is the MultiCAN message-object register base (MO0). From
 * fastboatster/TC1796 reg176x.h, where every offset matches our struct exactly:
 * CAN_MOFCR0=0xF0004600 (+0x00), MODATAL0=0xF0004610 (+0x10), MODATAH0=0xF0004614
 * (+0x14), MOCTR0=0xF000461C (+0x1C); MO1 at +0x20. TC1796 is the SAME AUDO-NG
 * family as TC1767 and shares its memory map, and the TC1767 datasheet peripheral
 * table (F000 40xxH) corroborates the 0xF0004xxx region.
 * NOTE: bri3d/TC1791 uses 0xF0005000, but TC1791 is AUDO-MAX (a DIFFERENT family)
 * -- its base does NOT apply to TC1767. TODO(bench): confirm on the part.
 */
/* CONFIRMED 2026-11-12 against the OFFICIAL Infineon AP32132 AUDO-F CANLoader
 * source (GNU/CANLoader/src/reg176x.h): the TC1767 MultiCAN message objects are
 * at base 0xF0005000 (MODATAL0=0xF0005010, MOFCR1=0xF0005020, MOCTR1=0xF000503C).
 * The earlier 0xF0004600 was the TC1796 value and WRONG for TC1767 -> every MO
 * access hit a dead address -> loader ran but CAN was silent (bench 2026-11-12).
 * (TC1791/AUDO-MAX also uses 0xF0005000; AUDO-F matches it, not AUDO-NG.) */
#define CAN_MSGOBJ_BASE   0xF0005000u
#define CAN_MO_STRIDE     0x20u

#define MO_FCR(n)     REG32(CAN_MSGOBJ_BASE + (n) * CAN_MO_STRIDE + 0x00u)
#define MO_DATAL(n)   REG32(CAN_MSGOBJ_BASE + (n) * CAN_MO_STRIDE + 0x10u)
#define MO_DATAH(n)   REG32(CAN_MSGOBJ_BASE + (n) * CAN_MO_STRIDE + 0x14u)
#define MO_CTR(n)     REG32(CAN_MSGOBJ_BASE + (n) * CAN_MO_STRIDE + 0x1Cu)  /* write: MOCTR */
#define MO_STAT(n)    REG32(CAN_MSGOBJ_BASE + (n) * CAN_MO_STRIDE + 0x1Cu)  /* read:  MOSTAT */

#define MO_RX   0u   /* receive message object (host -> loader) */
#define MO_TX   1u   /* transmit message object (loader -> host) */

/* MOSTAT / MOCTR bit fields (MultiCAN standard):
 *   MOSTAT.NEWDAT = bit 3 (0x08)  -- new data received
 *   MOSTAT.TXRQ   = bit 8 (0x100) -- transmit request pending
 * MOCTR is a set/reset command register: high half (bits 16..31) RESETs the
 * corresponding low-half (bits 0..15) status bit; low half SETs it.
 * TODO(bench): confirm these bit positions for the TC1767 MultiCAN revision.
 */
#define MO_NEWDAT     0x00000008u
#define MO_TXRQ       0x00000100u

/* MOCTR command words. The transmit kick 0x0F200000 and the TXRQ poll bit 0x100
 * are CONFIRMED against fastboatster/TC1796 (it writes CAN_MOCTR1 = 0x0F200000 to
 * request a transmit and polls `CAN_MOCTR1 & 0x00000100` for completion). The RX
 * NEWDAT-clear below (reset NEWDAT bit3 + keep MSGVAL/RXEN set) is plausible but
 * not pinned to fastboatster's RX path -- TODO(bench): confirm the reset encoding. */
#define MOCTR_SET_TXRQ_NEWDAT_MSGVAL  0x0F200000u  /* kick a transmit (confirmed TC1796) */
#define MOCTR_CLEAR_NEWDAT            0x00A00008u  /* ack a received frame (TODO bench) */

#endif /* GAMMAFLASH_TC1767_REGS_H */
