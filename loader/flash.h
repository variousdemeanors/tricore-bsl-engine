/*
 * flash.h -- TC1767 (AUDO-F) flash erase/program/unprotect for the GammaFlash
 * CANLoader write path (Plan 3). Like tc1767_regs.h, the hardware constants here
 * are confined to one file; the ones NOT independently confirmed are marked
 * TODO(bench) and must be checked against the TC1767 User Manual before the
 * write path is trusted on a live part.
 *
 * SOURCES (what is confirmed vs. flagged):
 *  - CONFIRMED by our own RE -- `hq/gammaflash-re/GHIDRA_PWD_CONSUMER_FINDINGS`
 *    (the ECU's native UCB flash-unlock routine `fn 0x80182756`) AND independently
 *    by `bri3d/TC1791_CAN_BSL` FLASH.c: the Command Sequence Interface (CSI) base
 *    0xA0000000 and the command offsets/cycles, and the exact unlock sequence
 *    (0x553C<-0, 0xAAA8<-word1, 0xAAA8<-word2, 0x5558<-8 then <-5).
 *  - UNLOCK KEYS: the host supplies the flash controller's own read/write key
 *    words (obtained from the PCMflash wire or a pcmflash crash dump). There is
 *    NO host-side pwd->key transform here -- that transform is PCMflash's dongle
 *    crypto (see EXTRACTED_UNLOCK_KEYS.md) and is deliberately NOT replicated.
 *  - TODO(bench): the DFlash command base, the FSR address + busy-bit layout, and
 *    that protection codes 8/5 are a temporary disable, NEVER an Install (UCB 4x wall).
 */
#ifndef GAMMAFLASH_TC1767_FLASH_H
#define GAMMAFLASH_TC1767_FLASH_H

#include "tc1767_regs.h"   /* u8/u16/u32, REG32 */

/* CSI bases. PFlash base CONFIRMED (0xA0000000). DFlash flagged. */
#define FLASH_PF_CSI_BASE   0xA0000000u   /* CONFIRMED (fn 0x80182756 + bri3d) */
#define FLASH_DF_CSI_BASE   0xAF000000u   /* TODO(bench): confirm DFlash command base vs TC1767 UM */

/* CSI register offsets (AUDO standard; CONFIRMED at 0xA000xxxx by our RE). */
#define CSI_CMD1   0x5554u   /* AA / 80 / A0 / 50 / F5 command cycles */
#define CSI_CMD2   0xAAA8u   /* 55 cycle + the two UCB password words */
#define CSI_UCB    0x553Cu   /* UCB selector (written 0) */
#define CSI_PROT   0x5558u   /* protection command code */
#define CSI_PAGE   0x55F0u   /* 64-bit assemble-page data port */

/* Flash command cycle data values. */
#define FC_RESET_STATUS   0x00F5u
#define FC_UNLOCK_AA      0x00AAu
#define FC_UNLOCK_55      0x0055u
#define FC_ERASE_SETUP    0x0080u
#define FC_ERASE_CONFIRM  0x0030u
#define FC_ENTER_PAGE     0x0050u
#define FC_WRITE_PAGE     0x00A0u
#define FC_PAGE_CONFIRM   0x00AAu

/* Protection-disable command codes (bri3d FLASH_PROTECTION; corroborated by the
 * pcmflash.DMP wire: af 00 08 = READ, af 00 05 = WRITE). Temporary disable, never Install. */
#define FLASH_PROT_READ    8u   /* disable READ protection (host sends the read key) */
#define FLASH_PROT_WRITE   5u   /* disable WRITE protection (host sends the write key) */

/* Flash Status Register. fn 0x80182756 reads 0xF8002010 as a mode/status reg
 * (tests bit 0x10000); treated here as the FSR. TODO(bench): confirm the FSR
 * address and the busy-bit positions against the TC1767 UM. */
#define FLASH_FSR          0xF8002010u   /* TODO(bench) */
#define FSR_PBUSY          0x00000001u   /* TODO(bench) */
#define FSR_D0BUSY         0x00000002u   /* TODO(bench) */
#define FSR_D1BUSY         0x00000004u   /* TODO(bench) */
#define FLASH_BUSY_MASK    (FSR_PBUSY | FSR_D0BUSY | FSR_D1BUSY)

/* Bounded busy-wait so a wrong FSR address/bit can NOT wedge the loader forever;
 * on timeout the op returns -1 and the host sees an erase/program error. */
#define FLASH_WAIT_LIMIT   4000000u

/* Erase the sector containing sector_addr. Returns 0 ok, -1 on busy-wait timeout. */
int flash_erase_sector(u32 csi_base, u32 sector_addr);

/* Program one 256-byte page at page_addr (sector must be pre-erased).
 * Returns 0 ok, -1 on busy-wait timeout. */
int flash_program_page(u32 csi_base, u32 page_addr, const u8 data[256]);

/* Temporary protection disable: one CSI pass sending the two key words for the
 * given protection command (FLASH_PROT_READ / FLASH_PROT_WRITE). The keys are the
 * flash controller's own unlock values, supplied by the host (NOT derived here --
 * PCMflash's .pwd->keys transform is the dongle's and is NOT replicated). NEVER installs. */
void flash_send_passwords(u32 csi_base, u16 prot_cmd, u32 word0, u32 word1, u16 ucb);

#endif /* GAMMAFLASH_TC1767_FLASH_H */
