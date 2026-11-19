/*
 * flash.h -- TC1767 (AUDO-F) flash erase/program/unprotect for the GammaFlash
 * CANLoader write path.
 *
 * AUTHORITATIVE SOURCE: the erase/program/FSR constants and the command-sequence
 * structure below are ported from Infineon's own AUDO-F CANLoader (AP32132
 * EraseSector / ProgramFlashPage), cross-checked with bri3d/TC1791_CAN_BSL and
 * our own RE of the ECU's native unlock routine `fn 0x80182756`.
 *
 * KEY FACTS confirmed on real silicon:
 *  - The CSI command base is NOT fixed: command cycles go to (addr & bank_mask).
 *    PFLASH bank mask ~0x1FFFFF, DFLASH bank mask ~0xFFFF -> e.g. 0xAFE00000.
 *    (A fixed command base outside the correct bank either traps on a bus error
 *    or issues a sequence that never arms the target bank -> erase no-op.)
 *  - DFLASH erase-confirm is 0x40 ("erase physical sector"), PFLASH is 0x30.
 *  - DFLASH enter-page is 0x5D, PFLASH is 0x50.
 *  - DFLASH page is 128 B; PFLASH page is 256 B.
 *  - FSR busy bits are PBUSY=0x01, D0BUSY=0x04, D1BUSY=0x08.
 *  - Command/confirm cycles are 32-bit writes.
 *
 * Unlock keys (PFLASH only) are supplied by the host; there is no pwd->key
 * transform here -- that transform is the commercial vendor tool's dongle
 * crypto and is deliberately NOT replicated. DFLASH needs no unlock.
 */
#ifndef GAMMAFLASH_TC1767_FLASH_H
#define GAMMAFLASH_TC1767_FLASH_H

#include "tc1767_regs.h"   /* u8/u16/u32, REG32 */

/* The flash Command Sequence Interface base is the BANK base of the target
 * address. PFLASH bank = 2 MB, DFLASH bank = 64 KB (AP32132 EraseSector). */
#define FLASH_PF_BASE_MASK  0xFFE00000u   /* ~0x1FFFFF : PFLASH 2 MB bank base */
#define FLASH_DF_BASE_MASK  0xFFFF0000u   /* ~0x0FFFF  : DFLASH 64 KB bank base */

#define FLASH_IS_PFLASH(a)  ((a) >= 0xA0000000u && (a) < 0xA0400000u)
#define FLASH_CMD_BASE(a)   (FLASH_IS_PFLASH(a) ? ((a) & FLASH_PF_BASE_MASK) \
                                                : ((a) & FLASH_DF_BASE_MASK))

/* PFLASH bank-0 CSI base, used only by flash_send_passwords (PFLASH unlock). */
#define FLASH_PF_CSI_BASE   0xA0000000u

/* CSI register offsets (from the bank base). */
#define CSI_CMD1   0x5554u   /* command cycles (F5/AA/80/A0/50/5D) */
#define CSI_CMD2   0xAAA8u   /* 55 cycle + the two UCB password words */
#define CSI_UCB    0x553Cu   /* UCB selector (written 0) */
#define CSI_PROT   0x5558u   /* protection command code */
#define CSI_PAGE   0x55F0u   /* 64-bit assemble-page data port */

/* Command cycle data values (AP32132). */
#define FC_CLEAR_STATUS   0x00F5u
#define FC_UNLOCK_AA      0x00AAu
#define FC_UNLOCK_55      0x0055u
#define FC_ERASE_SETUP    0x0080u
#define FC_ERASE_PF       0x0030u   /* PFLASH erase LOGICAL sector confirm */
#define FC_ERASE_DF       0x0040u   /* DFLASH erase PHYSICAL sector confirm */
#define FC_ENTER_PAGE_PF  0x0050u   /* PFLASH enter assemble-page mode */
#define FC_ENTER_PAGE_DF  0x005Du   /* DFLASH enter assemble-page mode */
#define FC_WRITE_PAGE     0x00A0u
#define FC_PAGE_CONFIRM   0x00AAu

/* Assemble-page sizes: DFLASH 128 B, PFLASH 256 B. The host still sends 256 B
 * payloads; for DFLASH the loader programs two 128 B pages per payload. */
#define PF_PAGE_SIZE   256u
#define DF_PAGE_SIZE   128u

/* Protection-disable command codes (flash-controller wire format:
 * af 00 08 = READ, af 00 05 = WRITE). Temporary disable, never Install. */
#define FLASH_PROT_READ    8u
#define FLASH_PROT_WRITE   5u

/* Flash Status Register. AP32132: PFLASH0_FSR == DFLASH_FSR == 0xF8002010
 * (PFLASH bank 1 would be 0xF8004010; not used here -- our targets are DFLASH
 * and PFLASH bank 0). Busy/error/protection bit layout from AP32132. */
#define FLASH_FSR          0xF8002010u
#define FSR_PBUSY          0x00000001u   /* Program Flash busy */
#define FSR_D0BUSY         0x00000004u   /* Data Flash bank 0 busy */
#define FSR_D1BUSY         0x00000008u   /* Data Flash bank 1 busy */
#define FLASH_BUSY_MASK    (FSR_PBUSY | FSR_D0BUSY | FSR_D1BUSY)   /* 0x0D */
#define FSR_PFOPER         0x00000100u   /* Program Flash operation error */
#define FSR_DFOPER         0x00000200u   /* Data Flash operation error */
#define FSR_SQER           0x00000400u   /* command Sequence error */
#define FLASH_ERROR_MASK   (FSR_PFOPER | FSR_DFOPER | FSR_SQER)    /* 0x700 */
#define FLASH_PROT_ERR     0x00000800u   /* protection error */
#define FSR_RPROIN         (1u << 18)    /* read protection installed */
#define FSR_RPRODIS        (1u << 19)    /* read protection temporarily disabled */
#define FSR_WPROIN0        (1u << 21)    /* sector write protection installed, user 0 */
#define FSR_WPRODIS0       (1u << 25)    /* sector write protection disabled, user 0 */

/* Bounded busy-wait so a wrong FSR address/bit can NOT spin the loader forever;
 * on timeout the op returns an error and the host sees an erase/program error.
 * A 256 KB PFLASH logical sector erases much longer than a 16 KB DFLASH one
 * (observed < 20 s): size this comfortably, or the loader can give up polling
 * while the silicon keeps erasing and report a false error. The watchdog is
 * disabled in crt0.S, so a long wait is safe; the host's own ACK timeout bounds
 * the wall-clock regardless. On a genuine stuck-busy this still returns -1. */
#define FLASH_WAIT_LIMIT   100000000u

/* Erase the physical sector containing sector_addr. Base + confirm value are
 * derived from the address (PFLASH vs DFLASH). Returns 0 ok; <0 on error:
 * -1 busy-wait timeout, -2 operation error, -3 protection error. */
int flash_erase_sector(u32 sector_addr);

/* Program one 256-byte host payload at page_addr (sector pre-erased). For
 * DFLASH this is two 128 B pages; for PFLASH one 256 B page. Same return codes. */
int flash_program_page(u32 page_addr, const u8 data[256]);

/* Temporary PFLASH protection disable: one CSI pass sending the two key words
 * for the given protection command (FLASH_PROT_READ / FLASH_PROT_WRITE). Keys are
 * the flash controller's own unlock values, supplied by the host -- NOT derived
 * here (the vendor tool's .pwd->keys transform is the dongle's and is NOT
 * replicated). NEVER installs. */
void flash_send_passwords(u32 csi_base, u16 prot_cmd, u32 word0, u32 word1, u16 ucb);
int flash_wait_done(void);

#endif /* GAMMAFLASH_TC1767_FLASH_H */
