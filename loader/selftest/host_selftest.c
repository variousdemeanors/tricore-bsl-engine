/*
 * host_selftest.c -- compiles the loader's PORTABLE block logic with the host
 * compiler so its wire output can be cross-checked against the Python golden
 * vector (see ../../test_loader_selftest.py). The hardware CAN layer, do_read's
 * address cast, and main() are excluded via LOADER_HOST_SELFTEST; the block
 * senders emit through CAN_TX, which we point at a capture buffer here.
 *
 * This validates exactly the parts most likely to carry a porting bug:
 * little-endian header decode, the XOR checksum domain, the 256-byte payload
 * padding, and the backup range gate. The CAN register pokes and startup remain
 * bench-only (unverifiable without the part + toolchain).
 *
 * Usage:
 *   ./host_selftest read <length>      # emit captured frames, hex, one per line
 *   ./host_selftest le32 <8 hex bytes> # print rd_le32 of those bytes
 *   ./host_selftest range <addr> <len> # print range_ok (0/1)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* capture sink for CAN_TX */
static unsigned char g_cap[1 << 20];
static unsigned g_cap_len;
static void capture_frame(const unsigned char *d) {
    memcpy(&g_cap[g_cap_len], d, 8);
    g_cap_len += 8;
}

#define LOADER_HOST_SELFTEST 1
#define CAN_TX(frame) capture_frame(frame)
#include "../main.c"

/* same deterministic pattern as the Python side (_IMG) */
static unsigned char pat(unsigned i) { return (unsigned char)((i * 7u + 3u) & 0xFFu); }

int main(int argc, char **argv) {
    if (argc >= 3 && strcmp(argv[1], "read") == 0) {
        unsigned length = (unsigned)strtoul(argv[2], NULL, 0);
        static unsigned char buf[0x8000];
        unsigned i, off;
        for (i = 0; i < sizeof(buf); i++)
            buf[i] = pat(i);
        g_cap_len = 0;
        for (off = 0; off < length; off += DATA_PAYLOAD) {       /* mirrors do_read */
            unsigned n = length - off;
            if (n > DATA_PAYLOAD) n = DATA_PAYLOAD;
            send_data_block(&buf[off], n);
        }
        send_eot();
        for (i = 0; i < g_cap_len; i += 8) {
            unsigned j;
            for (j = 0; j < 8; j++) printf("%02x", g_cap[i + j]);
            printf("\n");
        }
        return 0;
    }
    if (argc >= 3 && strcmp(argv[1], "le32") == 0) {
        unsigned char b[4]; unsigned v = (unsigned)strtoul(argv[2], NULL, 16);
        b[0] = v & 0xFF; b[1] = (v >> 8) & 0xFF; b[2] = (v >> 16) & 0xFF; b[3] = (v >> 24) & 0xFF;
        printf("%08x\n", rd_le32(b));
        return 0;
    }
    if (argc >= 4 && strcmp(argv[1], "range") == 0) {
        u32 addr = (u32)strtoul(argv[2], NULL, 0);
        u32 len = (u32)strtoul(argv[3], NULL, 0);
        printf("%d\n", range_ok(addr, len));
        return 0;
    }
    fprintf(stderr, "usage: %s read <len> | le32 <hex> | range <addr> <len>\n", argv[0]);
    return 2;
}
