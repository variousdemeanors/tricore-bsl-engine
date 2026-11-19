/*
 * tc1767_regs.h -- isolated, hardware-specific register definitions for the
 * GammaFlash TC1767 CANLoader. THIS is the only file whose constants are not
 * verified in simulation; every address below not marked CONFIRMED should be
 * cross-checked against the TC1767 User Manual before trusting it on new
 * hardware. The BSL logic in main.c is hardware-independent and sim-tested.
 *
 * MultiCAN handoff assumption (AP32132 CAN BSL):
 *   The BootROM's CAN bootstrap loader configures the CAN node (bit timing,
 *   auto-baud from the host init frame) and two message objects -- MO0 for
 *   receive (host -> loader) and MO1 for transmit (loader -> host) -- and jumps
 *   to our image with that configuration live. We therefore DO NOT re-init the
 *   node or bit timing; we only poll/drive NEWDAT and TXRQ on MO0/MO1. This
 *   mirrors fastboatster/TC1796_CAN_bootloader (a related, unlicensed AUDO-NG
 *   project; structure reference only, no code copied), which likewise never
 *   re-inits.
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
 * CONFIRMED against the official Infineon AP32132 AUDO-F CANLoader source: the
 * TC1767 MultiCAN message objects are at base 0xF0005000 (MODATAL0=0xF0005010,
 * MOFCR1=0xF0005020, MOCTR1=0xF000503C). A related AUDO family (TC1796) uses a
 * different base (0xF0004600) that does NOT apply here -- every MO access at
 * that base hits a dead address and the loader runs with CAN silent. (TC1791
 * also uses 0xF0005000; AUDO-F matches it, not AUDO-NG.)
 */
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
 */
#define MO_NEWDAT     0x00000008u
#define MO_TXRQ       0x00000100u

/* MOCTR command words. The transmit kick 0x0F200000 and the TXRQ poll bit 0x100
 * request a transmit and poll for completion (confirmed on real silicon). The
 * RX NEWDAT-clear below resets NEWDAT (bit3) while keeping MSGVAL/RXEN set. */
#define MOCTR_SET_TXRQ_NEWDAT_MSGVAL  0x0F200000u  /* kick a transmit */
#define MOCTR_CLEAR_NEWDAT            0x00A00008u  /* ack a received frame */

#endif /* GAMMAFLASH_TC1767_REGS_H */
