/*
 * asc_io.c -- TC1767 ASC0 byte transport for the GammaFlash ASC-serial loader.
 *
 * This replaces the MultiCAN frame layer (main.c can_* wrappers) with the
 * on-chip ASC0 UART. It is compiled into the loader with -DASC_TRANSPORT; the
 * command-block logic above it is byte-for-byte the same proven CAN loader
 * (main.c) -- only the 8-byte frame transport differs.
 *
 * The BootROM's autobaud settings are used through the loader upload. The
 * loader then switches to a higher baud for command and data traffic.
 *
 * ASC0 register map (TC1767 / AUDO-F, AP32132):
 *   ASC0_TBUF = 0xF0000A20   transmit buffer
 *   ASC0_RBUF = 0xF0000A24   receive buffer
 *   ASC0_TSRC = 0xF0000AF0   transmit service request control
 *   ASC0_RSRC = 0xF0000AF4   receive  service request control
 *
 * Service Request Control register bits -- TriCore 1.3 (TC1767/TC1796) layout,
 * which differs from AURIX (TC2xx/TC3xx bits 24/25/26). BENCH-CONFIRMED:
 *   bit 12 SRE  service request enable (leave set; the BootROM armed it)
 *   bit 13 SRR  service request flag (set by hardware, read)
 *   bit 14 CLRR write 1 to clear SRR
 *   bit 15 SETR write 1 to set SRR
 * Polling targets SRR(13); the clear is a READ-MODIFY-WRITE that sets CLRR(14)
 * while preserving SRPN/SRE -- a plain write of CLRR alone zeroes SRE and
 * disables the node (SRR then never sets again).
 */
#include "asc_io.h"

#define ASC0_CON  (*(volatile unsigned int *)0xF0000A10u)
#define ASC0_BG   (*(volatile unsigned int *)0xF0000A14u)
#define ASC0_FDV  (*(volatile unsigned int *)0xF0000A18u)
#define ASC0_TBUF (*(volatile unsigned int *)0xF0000A20u)
#define ASC0_RBUF (*(volatile unsigned int *)0xF0000A24u)
#define ASC0_TSRC (*(volatile unsigned int *)0xF0000AF0u)
#define ASC0_RSRC (*(volatile unsigned int *)0xF0000AF4u)

#define SRN_SRR  (1u << 13)   /* TC1.3 service request flag (read)  */
#define SRN_CLRR (1u << 14)   /* TC1.3 write 1 to clear SRR          */
#define ASC_CON_R (1u << 15)  /* run baud rate generator */
#define ASC_SWITCH_BAUD 0xA5u
#define ASC_DATA_SYNC   0x55u

void asc0_init(void)
{
    /* At a low upload baud, long low runs can trip a CAN transceiver's
     * dominant-bit timeout if the serial lines are carried over a CAN pair.
     * Announce the switch at the upload baud; the host's UART then switches
     * and sends a sync byte, which this loop waits for before going ready. */
    asc0_putc(ASC_SWITCH_BAUD);

    /* Preserve the BootROM's frame format and fractional-divider enable.
     * With a 10 MHz bench prescaler clock, the data rate is
     * 10 MHz * (205 / 512) / (16 * (0 + 1)) = ~250 kbaud. Adjust FDV for a
     * different source clock or target baud. */
    unsigned int config = ASC0_CON;
    ASC0_CON = config & ~ASC_CON_R;
    ASC0_BG = 0u;
    ASC0_FDV = 205u;
    ASC0_CON = config;

    while (asc0_getc() != ASC_DATA_SYNC) { }
}

uint8_t asc0_getc(void)
{
    while ((ASC0_RSRC & SRN_SRR) == 0u) { }   /* wait for a received byte */
    {
        uint8_t value = (uint8_t)ASC0_RBUF;   /* read clears the RBUF-full state */
        ASC0_RSRC |= SRN_CLRR;                /* clear the receive request flag */
        return value;
    }
}

void asc0_putc(uint8_t value)
{
    /* Write-then-wait: the transmit buffer is empty on entry, so write first
     * and then poll TSRC.SRR for transmit-complete. Waiting BEFORE the first
     * write would hang forever, because SRR is not pre-set at loader entry
     * (the transmit flag is set only AFTER a byte is sent). */
    ASC0_TBUF = (unsigned int)value;          /* buffer is free -> start the byte */
    while ((ASC0_TSRC & SRN_SRR) == 0u) { }   /* wait until it has been sent */
    ASC0_TSRC |= SRN_CLRR;                     /* clear for the next byte */

    /* HALF-DUPLEX: if the serial lines share a bus where your own transmitted
     * byte loops back into RBUF (e.g. carried over a two-wire pair wired for
     * half duplex), discard it here so it is never mistaken for a received
     * command byte. On a true point-to-point UART with no loopback this read
     * will simply never see a byte here and should be removed. */
    while ((ASC0_RSRC & SRN_SRR) == 0u) { }   /* wait for the looped-back byte */
    (void)ASC0_RBUF;                           /* read-discard the self-echo    */
    ASC0_RSRC |= SRN_CLRR;                      /* clear the RX flag (RMW)        */
}

void asc0_send(const uint8_t *data, uint32_t length)
{
    while (length-- != 0u)
        asc0_putc(*data++);
}
