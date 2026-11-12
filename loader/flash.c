/*
 * flash.c -- TC1767 (AUDO-F) flash erase/program/unprotect for the GammaFlash
 * CANLoader write path. The command sequences replicate the ECU's own native
 * unlock routine (fn 0x80182756, see flash.h SOURCES) and bri3d/TC1791_CAN_BSL.
 *
 * Unlock keys are supplied by the host (the flash controller's own values); there
 * is no pwd->key transform here -- that is PCMflash's dongle crypto, not replicated.
 */
#include "flash.h"

#ifndef LOADER_HOST_SELFTEST

#define CSI16(base, off, val)  (*(volatile u16 *)((base) + (off)) = (u16)(val))
#define CSI32(base, off, val)  (*(volatile u32 *)((base) + (off)) = (u32)(val))

/* Wait for the flash state machine to start (busy set) then finish (busy clear),
 * each bounded by FLASH_WAIT_LIMIT. Returns 0 if it completed, -1 on timeout. */
static int flash_wait_idle(void)
{
    u32 n = 0;
    while (((REG32(FLASH_FSR) & FLASH_BUSY_MASK) == 0u) && (++n < FLASH_WAIT_LIMIT)) { }
    if (n >= FLASH_WAIT_LIMIT)
        return -1;
    n = 0;
    while (((REG32(FLASH_FSR) & FLASH_BUSY_MASK) != 0u) && (++n < FLASH_WAIT_LIMIT)) { }
    return (n < FLASH_WAIT_LIMIT) ? 0 : -1;
}

int flash_erase_sector(u32 csi_base, u32 sector_addr)
{
    CSI16(csi_base, CSI_CMD1, FC_RESET_STATUS);
    CSI16(csi_base, CSI_CMD1, FC_UNLOCK_AA);
    CSI16(csi_base, CSI_CMD2, FC_UNLOCK_55);
    CSI16(csi_base, CSI_CMD1, FC_ERASE_SETUP);
    CSI16(csi_base, CSI_CMD1, FC_UNLOCK_AA);
    CSI16(csi_base, CSI_CMD2, FC_UNLOCK_55);
    *(volatile u16 *)sector_addr = FC_ERASE_CONFIRM;   /* erase confirm to the sector */
    return flash_wait_idle();
}

int flash_program_page(u32 csi_base, u32 page_addr, const u8 d[256])
{
    unsigned i;
    CSI16(csi_base, CSI_CMD1, FC_RESET_STATUS);
    CSI16(csi_base, CSI_CMD1, FC_ENTER_PAGE);          /* enter assemble-page mode */
    for (i = 0; i < 256u; i += 8u) {                   /* load 64 bits at a time */
        unsigned long long v =
              (unsigned long long)d[i]
            | ((unsigned long long)d[i + 1] << 8)
            | ((unsigned long long)d[i + 2] << 16)
            | ((unsigned long long)d[i + 3] << 24)
            | ((unsigned long long)d[i + 4] << 32)
            | ((unsigned long long)d[i + 5] << 40)
            | ((unsigned long long)d[i + 6] << 48)
            | ((unsigned long long)d[i + 7] << 56);
        *(volatile unsigned long long *)(csi_base + CSI_PAGE) = v;
    }
    CSI16(csi_base, CSI_CMD1, FC_UNLOCK_AA);
    CSI16(csi_base, CSI_CMD2, FC_UNLOCK_55);
    CSI16(csi_base, CSI_CMD1, FC_WRITE_PAGE);
    *(volatile u16 *)page_addr = FC_PAGE_CONFIRM;      /* write-page confirm to the page */
    return flash_wait_idle();
}

void flash_send_passwords(u32 csi_base, u16 prot_cmd, u32 word0, u32 word1, u16 ucb)
{
    /* One CSI pass: send the two key words then the protection command. Matches
     * bri3d FLASH_sendPasswords and the pcmflash.DMP wire (af 00 08/05 00 <key>).
     * The host calls this once for READ (FLASH_PROT_READ, read key, ucb 0) and once
     * for WRITE (FLASH_PROT_WRITE, write key, ucb 1). Temporary disable; never installs. */
    CSI16(csi_base, CSI_CMD1, FC_UNLOCK_AA);
    CSI16(csi_base, CSI_CMD2, FC_UNLOCK_55);
    CSI16(csi_base, CSI_UCB, ucb);
    CSI32(csi_base, CSI_CMD2, word0);
    CSI32(csi_base, CSI_CMD2, word1);
    CSI16(csi_base, CSI_PROT, prot_cmd);
}

#endif /* !LOADER_HOST_SELFTEST */
