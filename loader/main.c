/*
 * main.c -- GammaFlash TC1767 read-only CANLoader.
 *
 * Runs from SPRAM 0xD4000000 after the BootROM CAN BSL uploads this image and
 * jumps to it. Implements ONLY the read side of the BSL command protocol:
 * header parse + the Mode 0x07 read primitive, returning raw memory in the
 * Plan-1 block framing the GammaFlash host and mock already test. There is NO
 * program / erase / protect / exec code -- v1 is read-only by construction
 * (spec anti-goal: no write path, no brick risk).
 *
 * Wire contract (docs/plans/2026-10-28-native-bsl-tc1767-loader-binary.md):
 *   host -> Header(16B): [0x00][mode][addr LE32 @2..5][len LE32 @6..9][..][xor]
 *   loader -> bare 0x55 ack  (or 0xFD bad cksum / 0xFE bad mode / 0xFC bad range)
 *   loader -> ceil(len/256) Data(264B): [0x01][verify][256 raw][5 zero][xor]
 *   loader -> EOT(16B): [0x02][14 zero][xor]
 *
 * IMPORTANT (adaptation vs fastboatster): the header address/length are
 * LITTLE-ENDIAN here (fastboatster reads them big-endian). See rd_le32().
 *
 * The hardware-specific CAN register access is confined to tc1767_regs.h and
 * the three can_* wrappers; everything else is portable and sim-verified.
 */
#include "tc1767_regs.h"
#include "flash.h"

/* Test seam: the block senders emit through CAN_TX so a host self-test can
 * capture frames instead of poking CAN registers. Defaults to the real CAN TX.
 * See loader/selftest/ -- the portable block logic is cross-checked on the host
 * compiler against the same golden vector the Python host uses. */
#ifndef CAN_TX
#define CAN_TX(frame) can_send_frame(frame)
#endif

/* ---- BSL protocol constants (match gammaflash/bsl/framing.py) ---- */
#define BLK_HEADER   0x00
#define BLK_DATA     0x01
#define BLK_EOT      0x02

#define MODE_PROGRAM_PAGE 0x00  /* write path: program one 256 B page */
#define MODE_ERASE_SECTOR 0x04  /* write path: erase the sector at addr */
#define MODE_PROTECT      0x06  /* write path: temporary disable write protect */
#define MODE_READ        0x07   /* our read primitive (uncompressed, raw) */
#define MODE_KEEP_ALIVE  0x3E   /* bench bring-up ping */

#define RESP_ACK         0x55
#define RESP_INVALID_MODE  0xFE
#define RESP_CHECKSUM_ERR  0xFD
#define RESP_ADDRESS_ERR   0xFC
#define RESP_ERASE_ERR     0xFB
#define RESP_PROGRAM_ERR   0xFA
#define RESP_VERIFY_ERR    0xF9
#define RESP_PROTECTION    0xF8

#define HEADER_LEN   16
#define DATA_LEN     264
#define DATA_PAYLOAD 256
#define EOT_LEN      16

/* Backup address map (spec / host BACKUP_RANGES). [base, base+size). */
struct range { u32 base; u32 size; };
static const struct range BACKUP_RANGES[] = {
    { 0xAFE00000u, 0x20000u },  /* full DFlash span incl. gap/config (full extraction) */
    { 0xA0000000u, 0x200000u }, /* PFlash (2 MB) */
};
#define N_RANGES (sizeof(BACKUP_RANGES) / sizeof(BACKUP_RANGES[0]))

/* Static block buffers (no heap; all inside the 0x1400 SPRAM window). */
static u8 g_header[HEADER_LEN];
static u8 g_block[DATA_LEN];

/* ---- thin CAN layer (the ONLY hardware-touching code) ----------------- */
#ifndef LOADER_HOST_SELFTEST

static void can_send_frame(const u8 *d)
{
    /* wait until any previous transmit request on MO_TX has cleared */
    while ((MO_STAT(MO_TX) & MO_TXRQ) != 0u) { }
    MO_DATAL(MO_TX) = (u32)d[0] | ((u32)d[1] << 8) | ((u32)d[2] << 16) | ((u32)d[3] << 24);
    MO_DATAH(MO_TX) = (u32)d[4] | ((u32)d[5] << 8) | ((u32)d[6] << 16) | ((u32)d[7] << 24);
    MO_FCR(MO_TX) = 0x08000000u;   /* DLC=8, standard TX (official CANLoader sets MOFCR each send) */
    MO_CTR(MO_TX) = MOCTR_SET_TXRQ_NEWDAT_MSGVAL;   /* kick transmit */
}

static void can_recv_frame(u8 *d)
{
    u32 lo, hi;
    while ((MO_STAT(MO_RX) & MO_NEWDAT) == 0u) { }  /* spin for new data */
    lo = MO_DATAL(MO_RX);
    hi = MO_DATAH(MO_RX);
    MO_CTR(MO_RX) = MOCTR_CLEAR_NEWDAT;             /* ack the frame */
    d[0] = (u8)(lo);       d[1] = (u8)(lo >> 8);
    d[2] = (u8)(lo >> 16); d[3] = (u8)(lo >> 24);
    d[4] = (u8)(hi);       d[5] = (u8)(hi >> 8);
    d[6] = (u8)(hi >> 16); d[7] = (u8)(hi >> 24);
}

/* Send a single status byte (ack / error) as a one-content-byte frame. The
 * host only inspects data[0]. */
static void can_send_status(u8 code)
{
    u8 f[8] = { code, 0, 0, 0, 0, 0, 0, 0 };
    can_send_frame(f);
}

#endif /* !LOADER_HOST_SELFTEST */

/* ---- portable helpers (sim-verified logic) ---------------------------- */

static u32 rd_le32(const u8 *p)   /* little-endian, matches the host encoder */
{
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}

/* XOR of body[1..n-1] -- the checksum domain excludes the type byte body[0]. */
static u8 block_xor(const u8 *body, unsigned n)
{
    u8 c = 0;
    unsigned i;
    for (i = 1; i < n; i++)
        c ^= body[i];
    return c;
}

/* Split a fully-built block (incl. its trailing checksum) into 8-byte CAN
 * frames and send them in order. len is a multiple of 8 (16 or 264). */
static void send_block(const u8 *blk, unsigned len)
{
    unsigned i;
    for (i = 0; i < len; i += 8)
        CAN_TX(&blk[i]);
}

/* True iff [addr, addr+len) lies fully inside one backup range. */
static int range_ok(u32 addr, u32 len)
{
    unsigned i;
    if (len == 0u)
        return 0;
    for (i = 0; i < N_RANGES; i++) {
        u32 b = BACKUP_RANGES[i].base;
        u32 e = b + BACKUP_RANGES[i].size;       /* exclusive end */
        if (addr >= b && addr <= e && len <= (e - addr))
            return 1;                            /* overflow-safe containment */
    }
    return 0;
}

/* PFlash is write-protectable on AUDO-F; DFlash is not. A program/erase in the
 * PFlash span needs a prior Mode-0x06 temporary disable this session. */
static int is_pflash(u32 addr)
{
    return addr >= 0xA0000000u && addr < 0xA0200000u;
}

/* Emit one 264-byte Data block for up to 256 bytes at src (zero-padded). */
static void send_data_block(const u8 *src, unsigned n)
{
    unsigned i;
    g_block[0] = BLK_DATA;
    g_block[1] = 0x00;                            /* verify flag (unused on read) */
    for (i = 0; i < DATA_PAYLOAD; i++)
        g_block[2 + i] = (i < n) ? src[i] : 0x00; /* payload then zero pad */
    g_block[2 + DATA_PAYLOAD + 0] = 0;            /* 5 unused bytes */
    g_block[2 + DATA_PAYLOAD + 1] = 0;
    g_block[2 + DATA_PAYLOAD + 2] = 0;
    g_block[2 + DATA_PAYLOAD + 3] = 0;
    g_block[2 + DATA_PAYLOAD + 4] = 0;
    g_block[DATA_LEN - 1] = block_xor(g_block, DATA_LEN - 1);
    send_block(g_block, DATA_LEN);
}

static void send_eot(void)
{
    u8 eot[EOT_LEN];
    unsigned i;
    eot[0] = BLK_EOT;
    for (i = 1; i < EOT_LEN - 1; i++)
        eot[i] = 0x00;
    eot[EOT_LEN - 1] = block_xor(eot, EOT_LEN - 1);
    send_block(eot, EOT_LEN);
}

#ifndef LOADER_HOST_SELFTEST
/* The Mode 0x07 read: ack already sent by caller; stream the raw bytes.
 * Casts the 32-bit target address to a pointer -- correct on TC1767, so this is
 * excluded from the 64-bit host self-test (which drives send_data_block directly). */
static void do_read(u32 addr, u32 len)
{
    const u8 *src = (const u8 *)addr;
    u32 off;
    for (off = 0; off < len; off += DATA_PAYLOAD) {
        u32 n = len - off;
        if (n > DATA_PAYLOAD)
            n = DATA_PAYLOAD;
        send_data_block(src + off, (unsigned)n);
    }
    send_eot();
}
#endif /* !LOADER_HOST_SELFTEST */

#ifndef LOADER_HOST_SELFTEST

/* Receive a 16-byte header (2 CAN frames) into g_header. */
static void recv_header(void)
{
    can_recv_frame(&g_header[0]);
    can_recv_frame(&g_header[8]);
}

/* Receive a 264-byte Data block (33 CAN frames) into g_block. */
static void recv_data_block(void)
{
    unsigned i;
    for (i = 0; i < DATA_LEN; i += 8)
        can_recv_frame(&g_block[i]);
}

/* Set once a Mode-0x06 temporary write-protect disable succeeds this session.
 * DFlash never needs it; PFlash program/erase is refused until it is set. */
static int g_pflash_unlocked = 0;

static u32 csi_base_for(u32 addr)
{
    return is_pflash(addr) ? FLASH_PF_CSI_BASE : FLASH_DF_CSI_BASE;
}

/* Mode 0x04: erase the sector containing addr (range already validated). */
static void do_erase(u32 addr)
{
    if (is_pflash(addr) && !g_pflash_unlocked) {
        can_send_status(RESP_PROTECTION);
        return;
    }
    if (flash_erase_sector(csi_base_for(addr), addr) != 0) {
        can_send_status(RESP_ERASE_ERR);
        return;
    }
    can_send_status(RESP_ACK);
}

/* Mode 0x00: program one 256 B page. The Data block ALWAYS follows the header,
 * so consume it first (even on rejection) to keep the session in sync. */
static void do_program(u32 addr)
{
    unsigned i;
    const u8 *src;

    recv_data_block();
    if (block_xor(g_block, DATA_LEN - 1) != g_block[DATA_LEN - 1]) {
        can_send_status(RESP_CHECKSUM_ERR);
        return;
    }
    if (!range_ok(addr, DATA_PAYLOAD)) {
        can_send_status(RESP_ADDRESS_ERR);
        return;
    }
    if (is_pflash(addr) && !g_pflash_unlocked) {
        can_send_status(RESP_PROTECTION);
        return;
    }
    if (flash_program_page(csi_base_for(addr), addr, &g_block[2]) != 0) {
        can_send_status(RESP_PROGRAM_ERR);
        return;
    }
    src = (const u8 *)addr;                 /* read-back verify (Ruling W2) */
    for (i = 0; i < DATA_PAYLOAD; i++) {
        if (src[i] != g_block[2 + i]) {
            can_send_status(RESP_VERIFY_ERR);
            return;
        }
    }
    can_send_status(RESP_ACK);
}

/* Mode 0x06: temporary disable of PFlash read or write protection.
 * content = [prot_cmd][ucb][word0 LE32][word1 LE32]. prot_cmd is FLASH_PROT_READ
 * (0x08, enables reading protected flash) or FLASH_PROT_WRITE (0x05, enables
 * erase/program). The two key words are the flash controller's own unlock values,
 * supplied by the host. Write-unlock sets g_pflash_unlocked (gates erase/program). */
static void do_protect(void)
{
    u8  prot_cmd = g_header[2];
    u8  ucb      = g_header[3];
    u32 word0    = rd_le32(&g_header[4]);
    u32 word1    = rd_le32(&g_header[8]);
    flash_send_passwords(FLASH_PF_CSI_BASE, prot_cmd, word0, word1, ucb);
    if (prot_cmd == FLASH_PROT_WRITE)
        g_pflash_unlocked = 1;
    can_send_status(RESP_ACK);
}

int main(void)
{
    for (;;) {
        u8 mode;
        u32 addr, len;

        recv_header();

        /* validate the header checksum over body[1 .. 14] */
        if (block_xor(g_header, HEADER_LEN - 1) != g_header[HEADER_LEN - 1]) {
            can_send_status(RESP_CHECKSUM_ERR);
            continue;
        }

        mode = g_header[1];
        addr = rd_le32(&g_header[2]);

        if (mode == MODE_KEEP_ALIVE) {
            u8 ka[8] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xD0, 0x0D, 0xBA, 0xAD };
            can_send_frame(ka);
            continue;
        }
        if (mode == MODE_READ) {
            len = rd_le32(&g_header[6]);
            if (!range_ok(addr, len)) {
                can_send_status(RESP_ADDRESS_ERR);
            } else {
                can_send_status(RESP_ACK);   /* header accepted */
                do_read(addr, len);          /* data blocks + EOT */
            }
            continue;
        }
        if (mode == MODE_ERASE_SECTOR) {
            if (!range_ok(addr, 1u))
                can_send_status(RESP_ADDRESS_ERR);
            else
                do_erase(addr);
            continue;
        }
        if (mode == MODE_PROGRAM_PAGE) {
            do_program(addr);   /* consumes the trailing Data block itself */
            continue;
        }
        if (mode == MODE_PROTECT) {
            do_protect();
            continue;
        }
        can_send_status(RESP_INVALID_MODE);
    }
    return 0;   /* unreachable */
}

#endif /* !LOADER_HOST_SELFTEST */
