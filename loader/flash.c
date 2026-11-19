/*
 * flash.c -- TC1767 (AUDO-F) flash erase/program/unprotect for the GammaFlash
 * CANLoader write path. The erase/program sequences, command values, page sizes
 * and FSR polling are ported from Infineon's own AUDO-F CANLoader (AP32132
 * EraseSector / ProgramFlashPage) -- see flash.h for the authoritative-source
 * notes.
 *
 * Unlock keys are supplied by the host (the flash controller's own values); there
 * is no pwd->key transform here -- that transform is the commercial vendor tool's
 * dongle crypto and is deliberately NOT replicated. DFLASH needs no unlock (it is
 * not write-protectable); PFLASH program/erase needs a prior Mode-0x06 temporary
 * disable (flash_send_passwords) this session.
 */
#include "flash.h"

#ifndef LOADER_HOST_SELFTEST

/* All command/confirm cycles are 32-bit writes (AP32132 uses DWORD writes). */
#define CSI32(base, off, val)  (*(volatile u32 *)((base) + (off)) = (u32)(val))

/* Wait (bounded) for the flash state machine to go idle, then classify from the
 * FSR. AP32132 polls busy-clear (it does NOT first wait for busy to SET -- a
 * rejected command leaves busy clear and is caught by the error bits). Returns
 * 0 ok, -1 busy-wait timeout, -2 operation error, -3 protection error. */
int flash_wait_done(void)
{
    u32 n = 0;
    u32 status;
    while (((REG32(FLASH_FSR) & FLASH_BUSY_MASK) != 0u) && (++n < FLASH_WAIT_LIMIT)) { }
    if (n >= FLASH_WAIT_LIMIT)
        return -1;
    status = REG32(FLASH_FSR);
    if ((status & FLASH_PROT_ERR) != 0u)
        return -3;
    if ((status & FLASH_ERROR_MASK) != 0u)
        return -2;
    return 0;
}

int flash_erase_sector(u32 sector_addr)
{
    u32 base    = FLASH_CMD_BASE(sector_addr);
    u32 confirm = FLASH_IS_PFLASH(sector_addr) ? FC_ERASE_PF : FC_ERASE_DF;

    CSI32(base, CSI_CMD1, FC_CLEAR_STATUS);
    CSI32(base, CSI_CMD1, FC_UNLOCK_AA);
    CSI32(base, CSI_CMD2, FC_UNLOCK_55);
    CSI32(base, CSI_CMD1, FC_ERASE_SETUP);
    CSI32(base, CSI_CMD1, FC_UNLOCK_AA);
    CSI32(base, CSI_CMD2, FC_UNLOCK_55);
    *(volatile u32 *)sector_addr = confirm;   /* erase confirm to the sector */
    return flash_wait_done();
}

/* Program ONE assemble-page (pagesize bytes from d) at page_addr. */
static int flash_program_one(u32 page_addr, const u8 *d, unsigned pagesize, int pflash)
{
    u32 base = FLASH_CMD_BASE(page_addr);
    unsigned i;

    CSI32(base, CSI_CMD1, FC_CLEAR_STATUS);
    CSI32(base, CSI_CMD1, pflash ? FC_ENTER_PAGE_PF : FC_ENTER_PAGE_DF);
    for (i = 0; i < pagesize; i += 8u) {               /* load 64 bits at a time */
        unsigned long long v =
              (unsigned long long)d[i]
            | ((unsigned long long)d[i + 1] << 8)
            | ((unsigned long long)d[i + 2] << 16)
            | ((unsigned long long)d[i + 3] << 24)
            | ((unsigned long long)d[i + 4] << 32)
            | ((unsigned long long)d[i + 5] << 40)
            | ((unsigned long long)d[i + 6] << 48)
            | ((unsigned long long)d[i + 7] << 56);
        *(volatile unsigned long long *)(base + CSI_PAGE) = v;
    }
    CSI32(base, CSI_CMD1, FC_UNLOCK_AA);
    CSI32(base, CSI_CMD2, FC_UNLOCK_55);
    CSI32(base, CSI_CMD1, FC_WRITE_PAGE);
    *(volatile u32 *)page_addr = FC_PAGE_CONFIRM;      /* write-page confirm */
    return flash_wait_done();
}

int flash_program_page(u32 page_addr, const u8 d[256])
{
    if (FLASH_IS_PFLASH(page_addr))
        return flash_program_one(page_addr, d, PF_PAGE_SIZE, 1);

    /* DFLASH: a 256 B host payload is two 128 B DFLASH pages. */
    {
        int r = flash_program_one(page_addr, d, DF_PAGE_SIZE, 0);
        if (r != 0)
            return r;
        return flash_program_one(page_addr + DF_PAGE_SIZE,
                                 d + DF_PAGE_SIZE, DF_PAGE_SIZE, 0);
    }
}

void flash_send_passwords(u32 csi_base, u16 prot_cmd, u32 word0, u32 word1, u16 ucb)
{
    /* One CSI pass: send the two key words then the protection command.
     * Matches the flash-controller wire format (af 00 08/05 00 <key>).
     * Temporary disable; never installs. PFLASH only. */
    CSI32(csi_base, CSI_CMD1, FC_CLEAR_STATUS);
    CSI32(csi_base, CSI_CMD1, FC_UNLOCK_AA);
    CSI32(csi_base, CSI_CMD2, FC_UNLOCK_55);
    CSI32(csi_base, CSI_UCB, ucb);
    CSI32(csi_base, CSI_CMD2, word0);
    CSI32(csi_base, CSI_CMD2, word1);
    CSI32(csi_base, CSI_PROT, prot_cmd);
}

#endif /* !LOADER_HOST_SELFTEST */
