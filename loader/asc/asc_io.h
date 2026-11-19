#ifndef GAMMAFLASH_ASC_IO_H
#define GAMMAFLASH_ASC_IO_H

#include <stdint.h>

/* TC1767 ASC0 transport used by the AP32132 loader command loop when built
 * with -DASC_TRANSPORT (see main.c). */
void asc0_init(void);
uint8_t asc0_getc(void);
void asc0_putc(uint8_t value);
void asc0_send(const uint8_t *data, uint32_t length);

#endif
