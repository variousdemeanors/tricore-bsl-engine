"""
TC1767 BSL-engine session: compose the wire protocol + a transport into the
operations the loader supports -- keep-alive, read, erase, program, write
(erase+program), verify, and temporary protection-disable (unlock).

Nothing here derives keys or secrets; PFLASH unlock words are supplied by the
operator (see NOTICE). Every op maps 1:1 to a loader mode in loader/main.c.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import protocol as p


class EngineError(RuntimeError):
    pass


def _check_ack(code, what):
    if code != p.RESP_ACK:
        raise EngineError(f"{what}: loader replied {p.status_name(code)} (0x{code:02x})")


@dataclass
class VerifyResult:
    ok: bool
    length: int
    first_mismatch: int = -1


class Session:
    def __init__(self, transport, pace_progress=None):
        self.t = transport
        self._progress = pace_progress or (lambda *_: None)

    # ---- bring-up ---------------------------------------------------------
    def enter_bootloader(self, loader_bin: bytes, **kw):
        """Enter the BootROM BSL and upload the loader. Caller power-cycles the
        ECU on cue (CAN) during the INIT flood."""
        self.t.enter_and_upload(loader_bin, **kw)

    def keep_alive(self, timeout=3.0) -> bool:
        """Mode 0x3E -> expect DE AD BE EF D0 0D BA AD. True iff the loader is alive."""
        self.t.send_block(p.build_header(p.MODE_KEEP_ALIVE))
        reply = self.t.read_frames(8, timeout=timeout)
        return reply == p.KEEP_ALIVE_REPLY

    def require_alive(self):
        if not self.keep_alive():
            raise EngineError(
                "loader not responding to keep-alive. Run `connect` first "
                "(the ECU must be freshly reset to enter the BootROM BSL).")

    # ---- read -------------------------------------------------------------
    def read(self, addr: int, length: int, timeout=5.0, on_block=None) -> bytes:
        if not p.in_backup_range(addr, length):
            raise EngineError(
                f"read [{addr:#010x}, +{length:#x}) is outside the loader's "
                f"backup ranges (DFLASH 2x32K, PFLASH 2M).")
        self.t.send_block(p.build_header(p.MODE_READ, addr, length))
        _check_ack(self.t.read_status(timeout), "read header")
        out = bytearray()
        nblocks = (length + p.DATA_PAYLOAD - 1) // p.DATA_PAYLOAD
        for i in range(nblocks):
            block = self.t.read_frames(p.DATA_LEN, timeout)
            out += p.parse_data_block(block)
            if on_block:
                on_block(i + 1, nblocks)
        eot = self.t.read_frames(p.EOT_LEN, timeout)
        if not p.is_eot(eot):
            raise EngineError("expected EOT block after read data, got "
                              f"type 0x{eot[0]:02x}")
        return bytes(out[:length])

    # ---- erase ------------------------------------------------------------
    def erase_sector(self, addr: int, timeout=4.0):
        """Mode 0x04: erase the flash sector containing addr."""
        if not p.in_backup_range(addr, 1):
            raise EngineError(f"erase addr {addr:#010x} outside backup ranges")
        self.t.send_block(p.build_header(p.MODE_ERASE_SECTOR, addr))
        _check_ack(self.t.read_status(timeout), f"erase {addr:#010x}")

    # ---- program ----------------------------------------------------------
    def program_page(self, addr: int, payload: bytes, timeout=4.0):
        """Mode 0x00: program one 256-byte page. The loader read-back-verifies it."""
        if len(payload) > p.DATA_PAYLOAD:
            raise EngineError("page payload > 256 bytes")
        self.t.send_block(p.build_header(p.MODE_PROGRAM_PAGE, addr, p.DATA_PAYLOAD))
        self.t.send_block(p.build_data_block(payload))
        _check_ack(self.t.read_status(timeout), f"program page {addr:#010x}")

    # ---- unlock (temporary protection disable) ----------------------------
    def unlock(self, word0: int, word1: int, ucb=0, read_protection=False,
               timeout=4.0):
        """Mode 0x06: temporarily disable WRITE (default) or READ protection with
        the chip's own key words (operator-supplied; never derived -- see NOTICE)."""
        prot = p.PROT_DISABLE_READ if read_protection else p.PROT_DISABLE_WRITE
        self.t.send_block(p.build_protect_header(prot, word0, word1, ucb))
        _check_ack(self.t.read_status(timeout),
                   "unlock read" if read_protection else "unlock write")

    # ---- high-level write (erase + program) -------------------------------
    def _dflash_bank_bases(self, addr, length):
        bases = []
        for base, size in (p.DFLASH_BANK0, p.DFLASH_BANK1):
            if addr < base + size and addr + length > base:
                bases.append(base)
        return bases

    def write(self, addr: int, data: bytes, do_erase=True, pflash_sectors=None,
              pad=0xFF, on_page=None):
        """Erase (if requested) then program `data` starting at addr, 256 B/page.
        The loader verifies each page by read-back on program.

        DFLASH: the containing 32 KB bank(s) are erased automatically.
        PFLASH: this engine does NOT guess the sector map -- pass the sector base
        addresses to erase via `pflash_sectors`, or do_erase=False to program into
        already-erased flash. (A protected PFLASH also needs a prior unlock().)"""
        length = len(data)
        if not p.in_backup_range(addr, length):
            raise EngineError(
                f"write [{addr:#010x}, +{length:#x}) is outside the loader's ranges")
        if length % p.DATA_PAYLOAD and pad is None:
            raise EngineError("write length not a multiple of 256 and pad disabled")

        if do_erase:
            if p.is_pflash(addr):
                if not pflash_sectors:
                    raise EngineError(
                        "PFLASH write needs explicit --erase-sectors <addr,...> "
                        "(this engine will not guess the PFLASH sector map), or "
                        "use --no-erase to program pre-erased flash.")
                for s in pflash_sectors:
                    self.erase_sector(s)
            else:
                for base in self._dflash_bank_bases(addr, length):
                    self.erase_sector(base)

        npages = (length + p.DATA_PAYLOAD - 1) // p.DATA_PAYLOAD
        for i in range(npages):
            off = i * p.DATA_PAYLOAD
            page = data[off:off + p.DATA_PAYLOAD]
            if len(page) < p.DATA_PAYLOAD:
                page = page + bytes((pad,)) * (p.DATA_PAYLOAD - len(page))
            self.program_page(addr + off, page)
            if on_page:
                on_page(i + 1, npages)

    # ---- verify -----------------------------------------------------------
    def verify(self, addr: int, data: bytes, on_block=None) -> VerifyResult:
        """Read back `len(data)` bytes at addr and compare."""
        got = self.read(addr, len(data), on_block=on_block)
        if got == data:
            return VerifyResult(ok=True, length=len(data))
        for i, (a, b) in enumerate(zip(got, data)):
            if a != b:
                return VerifyResult(ok=False, length=len(data), first_mismatch=i)
        return VerifyResult(ok=False, length=len(data), first_mismatch=min(len(got), len(data)))


def load_loader_bin(path) -> bytes:
    if not os.path.exists(path):
        raise EngineError(
            f"loader image not found: {path}. Build it first: "
            f"`./tricore-bsl-engine build` (or --setup).")
    with open(path, "rb") as f:
        return f.read()
