"""
TC1767 BSL-engine wire protocol -- pure, transport-agnostic logic.

This module is the host-side mirror of the loader's block protocol
(`loader/main.c`). It has NO I/O and NO dependencies, so it can be unit-tested
and cross-checked byte-for-byte against the loader's own C self-test
(`loader/selftest/host_selftest.c`). Everything hardware-touching lives in
transport.py / session.py.

Block formats (see docs/IMPLEMENTATION_GUIDE.md section 3):

  Header (16 B): [0x00][mode][addr LE32][len LE32][pad..][xor]
  Data   (264 B): [0x01][verifyflag][256 payload][5 pad][xor]
  EOT    (16 B): [0x02][zeros..][xor]

Checksum = XOR of every block byte EXCEPT the leading type byte and the
trailing checksum byte.
"""

from __future__ import annotations

# ---- block type bytes -------------------------------------------------------
BLK_HEADER = 0x00
BLK_DATA = 0x01
BLK_EOT = 0x02

# ---- command modes (header byte 1) -----------------------------------------
MODE_PROGRAM_PAGE = 0x00  # program one 256 B page (a Data block must follow)
MODE_ERASE_SECTOR = 0x04  # erase the flash sector containing addr
MODE_PROTECT = 0x06       # temporary disable of read/write protection
MODE_READ = 0x07          # raw block read
MODE_KEEP_ALIVE = 0x3E    # liveness ping

# ---- loader status bytes ----------------------------------------------------
RESP_ACK = 0x55
RESP_INVALID_MODE = 0xFE
RESP_CHECKSUM_ERR = 0xFD
RESP_ADDRESS_ERR = 0xFC
RESP_ERASE_ERR = 0xFB
RESP_PROGRAM_ERR = 0xFA
RESP_VERIFY_ERR = 0xF9
RESP_PROTECTION = 0xF8

STATUS_NAMES = {
    RESP_ACK: "ACK",
    RESP_INVALID_MODE: "invalid-mode",
    RESP_CHECKSUM_ERR: "checksum-error",
    RESP_ADDRESS_ERR: "address-out-of-range",
    RESP_ERASE_ERR: "erase-failed",
    RESP_PROGRAM_ERR: "program-failed",
    RESP_VERIFY_ERR: "verify-failed",
    RESP_PROTECTION: "protection (locked / wrong key)",
}

# ---- protect sub-commands (Mode 0x06) --------------------------------------
PROT_DISABLE_READ = 0x08   # temporarily disable read protection
PROT_DISABLE_WRITE = 0x05  # temporarily disable write protection (enables erase/program)

# ---- block geometry (must match the loader) --------------------------------
HEADER_LEN = 16
DATA_LEN = 264
DATA_PAYLOAD = 256
EOT_LEN = 16
KEEP_ALIVE_REPLY = bytes.fromhex("DEADBEEFD00DBAAD")

# ---- TC1767 memory map / backup+write ranges (loader BACKUP_RANGES) ---------
# The loader refuses any read/erase/program outside these ranges (RESP_ADDRESS_ERR).
DFLASH_BANK0 = (0xAFE00000, 0x8000)   # EEPROM bank 0, 32 KB, one erase sector
DFLASH_BANK1 = (0xAFE10000, 0x8000)   # EEPROM bank 1, 32 KB, one erase sector
PFLASH = (0xA0000000, 0x200000)       # program flash, 2 MB (protection is per-chip)
BACKUP_RANGES = (DFLASH_BANK0, DFLASH_BANK1, PFLASH)

PFLASH_BASE = 0xA0000000
PFLASH_END = 0xA0400000  # loader's FLASH_IS_PFLASH upper bound


def is_pflash(addr: int) -> bool:
    return PFLASH_BASE <= addr < PFLASH_END


def in_backup_range(addr: int, length: int) -> bool:
    """Mirror of the loader's range_ok(): [addr, addr+len) fully inside one range."""
    if length == 0:
        return False
    for base, size in BACKUP_RANGES:
        end = base + size  # exclusive
        if base <= addr <= end and length <= (end - addr):
            return True
    return False


def block_xor(body: bytes, n: int) -> int:
    """XOR of body[1:n] -- the checksum domain excludes the type byte body[0]."""
    c = 0
    for i in range(1, n):
        c ^= body[i]
    return c & 0xFF


def _le32(v: int) -> bytes:
    return bytes((v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF))


def build_header(mode: int, addr: int = 0, length: int = 0) -> bytes:
    """16-byte header block: [0x00][mode][addr LE32][len LE32][pad..][xor]."""
    b = bytearray(HEADER_LEN)
    b[0] = BLK_HEADER
    b[1] = mode & 0xFF
    b[2:6] = _le32(addr)
    b[6:10] = _le32(length)
    # bytes 10..14 stay zero (pad)
    b[HEADER_LEN - 1] = block_xor(b, HEADER_LEN - 1)
    return bytes(b)


def build_protect_header(prot_cmd: int, word0: int, word1: int, ucb: int = 0) -> bytes:
    """Mode 0x06 header carries [0x00][0x06][prot_cmd][ucb][word0 LE32][word1 LE32][..][xor].

    The loader reads prot_cmd=g_header[2], ucb=g_header[3], word0=g_header[4:8],
    word1=g_header[8:12]. The two key words are the flash controller's own unlock
    values, supplied by the operator -- never derived here (see NOTICE).
    """
    b = bytearray(HEADER_LEN)
    b[0] = BLK_HEADER
    b[1] = MODE_PROTECT
    b[2] = prot_cmd & 0xFF
    b[3] = ucb & 0xFF
    b[4:8] = _le32(word0)
    b[8:12] = _le32(word1)
    b[HEADER_LEN - 1] = block_xor(b, HEADER_LEN - 1)
    return bytes(b)


def build_data_block(payload: bytes, verify_flag: int = 0) -> bytes:
    """264-byte Data block for up to 256 payload bytes (zero-padded), matching
    the loader's send_data_block()."""
    if len(payload) > DATA_PAYLOAD:
        raise ValueError("data payload exceeds 256 bytes")
    b = bytearray(DATA_LEN)
    b[0] = BLK_DATA
    b[1] = verify_flag & 0xFF
    b[2:2 + len(payload)] = payload           # remainder already zero (pad)
    b[DATA_LEN - 1] = block_xor(b, DATA_LEN - 1)
    return bytes(b)


def build_eot() -> bytes:
    b = bytearray(EOT_LEN)
    b[0] = BLK_EOT
    b[EOT_LEN - 1] = block_xor(b, EOT_LEN - 1)
    return bytes(b)


def parse_data_block(block: bytes) -> bytes:
    """Validate a 264-byte Data block's checksum and return its 256-byte payload."""
    if len(block) != DATA_LEN:
        raise ValueError(f"data block must be {DATA_LEN} bytes, got {len(block)}")
    if block[0] != BLK_DATA:
        raise ValueError(f"not a Data block (type 0x{block[0]:02x})")
    if block_xor(block, DATA_LEN - 1) != block[DATA_LEN - 1]:
        raise ValueError("data block checksum mismatch")
    return bytes(block[2:2 + DATA_PAYLOAD])


def is_eot(block: bytes) -> bool:
    return len(block) >= 1 and block[0] == BLK_EOT


def status_name(code: int) -> str:
    return STATUS_NAMES.get(code, f"unknown-0x{code:02x}")
