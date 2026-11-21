"""
End-to-end test of the host session/engine against a MOCK loader that mirrors
loader/main.c semantics (range gate, erase-to-0x00, program+readback, keep-alive,
read->data blocks+EOT). No hardware. Validates read / write / verify / erase /
unlock / keep-alive wiring.

Run: python3 host/tests/test_session.py   (or pytest)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "host"))

from tc1767 import protocol as p          # noqa: E402
from tc1767 import session as se          # noqa: E402


class MockLoader:
    """A byte-stream transport (ASC-style: status=1 byte, block=raw bytes) backed
    by a flash model that enforces the same rules as the real loader."""

    def __init__(self, unlocked=False):
        # DFLASH two banks, PFLASH one 2 MB region; start erased (0x00, per TC1767).
        self.mem = {
            p.DFLASH_BANK0[0]: bytearray(b"\x00" * p.DFLASH_BANK0[1]),
            p.DFLASH_BANK1[0]: bytearray(b"\x00" * p.DFLASH_BANK1[1]),
            p.PFLASH[0]: bytearray(b"\x00" * p.PFLASH[1]),
        }
        self.unlocked = unlocked
        self.outq = bytearray()
        self._pending_prog = None

    # region lookup
    def _region(self, addr):
        for base, size in (p.DFLASH_BANK0, p.DFLASH_BANK1, p.PFLASH):
            if base <= addr < base + size:
                return base, self.mem[base]
        return None, None

    def _is_pflash(self, addr):
        return p.is_pflash(addr)

    # transport surface --------------------------------------------------
    def open(self):
        return self

    def close(self):
        pass

    def enter_and_upload(self, loader_bin, **kw):
        pass  # pretend the loader is uploaded and running

    def read_status(self, timeout=3.0):
        assert self.outq, "no status queued"
        return self.outq.pop(0)

    def read_frames(self, n, timeout=3.0):
        assert len(self.outq) >= n, f"short read {len(self.outq)}<{n}"
        chunk = bytes(self.outq[:n])
        del self.outq[:n]
        return chunk

    def send_block(self, block):
        if self._pending_prog is not None:
            self._do_program(block)
            return
        typ = block[0]
        assert typ == p.BLK_HEADER
        if p.block_xor(block, p.HEADER_LEN - 1) != block[p.HEADER_LEN - 1]:
            self.outq.append(p.RESP_CHECKSUM_ERR)
            return
        mode = block[1]
        addr = int.from_bytes(block[2:6], "little")
        length = int.from_bytes(block[6:10], "little")
        if mode == p.MODE_KEEP_ALIVE:
            self.outq += p.KEEP_ALIVE_REPLY
        elif mode == p.MODE_READ:
            self._do_read(addr, length)
        elif mode == p.MODE_ERASE_SECTOR:
            self._do_erase(addr)
        elif mode == p.MODE_PROGRAM_PAGE:
            self._pending_prog = addr          # data block follows
        elif mode == p.MODE_PROTECT:
            self.unlocked = True
            self.outq.append(p.RESP_ACK)
        else:
            self.outq.append(p.RESP_INVALID_MODE)

    # ops ----------------------------------------------------------------
    def _do_read(self, addr, length):
        if not p.in_backup_range(addr, length):
            self.outq.append(p.RESP_ADDRESS_ERR)
            return
        self.outq.append(p.RESP_ACK)
        base, buf = self._region(addr)
        off0 = addr - base
        off = 0
        while off < length:
            chunk = bytes(buf[off0 + off: off0 + off + p.DATA_PAYLOAD])
            self.outq += p.build_data_block(chunk)
            off += p.DATA_PAYLOAD
        self.outq += p.build_eot()

    def _do_erase(self, addr):
        if self._is_pflash(addr) and not self.unlocked:
            self.outq.append(p.RESP_PROTECTION)
            return
        base, buf = self._region(addr)
        if buf is None:
            self.outq.append(p.RESP_ADDRESS_ERR)
            return
        if self._is_pflash(addr):
            # erase a 16K logical sector for the mock
            s = (addr - base) & ~0x3FFF
            buf[s:s + 0x4000] = b"\x00" * 0x4000
        else:
            buf[:] = b"\x00" * len(buf)        # whole 32K bank
        self.outq.append(p.RESP_ACK)

    def _do_program(self, block):
        addr = self._pending_prog
        self._pending_prog = None
        if block[0] != p.BLK_DATA or \
           p.block_xor(block, p.DATA_LEN - 1) != block[p.DATA_LEN - 1]:
            self.outq.append(p.RESP_CHECKSUM_ERR)
            return
        payload = block[2:2 + p.DATA_PAYLOAD]
        if not p.in_backup_range(addr, p.DATA_PAYLOAD):
            self.outq.append(p.RESP_ADDRESS_ERR)
            return
        if self._is_pflash(addr) and not self.unlocked:
            self.outq.append(p.RESP_PROTECTION)
            return
        base, buf = self._region(addr)
        o = addr - base
        buf[o:o + p.DATA_PAYLOAD] = payload
        self.outq.append(p.RESP_ACK)


def _run(fn):
    try:
        fn()
        print(f"PASS {fn.__name__}")
        return True
    except Exception:
        import traceback
        print(f"FAIL {fn.__name__}")
        traceback.print_exc()
        return False


def test_keepalive():
    s = se.Session(MockLoader())
    assert s.keep_alive() is True


def test_read_write_verify_dflash_roundtrip():
    mock = MockLoader()
    s = se.Session(mock)
    img = bytes((i * 13 + 7) & 0xFF for i in range(p.DFLASH_BANK0[1]))  # 32K
    s.write(0xAFE00000, img)                       # auto-erase bank + program
    r = s.verify(0xAFE00000, img)
    assert r.ok, r
    back = s.read(0xAFE00000, len(img))
    assert back == img


def test_read_range_rejected():
    s = se.Session(MockLoader())
    try:
        s.read(0xAFE08000, 16)                     # the unimplemented gap
        assert False, "should have raised"
    except se.EngineError:
        pass


def test_pflash_write_needs_unlock_and_sectors():
    mock = MockLoader(unlocked=False)
    s = se.Session(mock)
    # locked -> program refused
    try:
        s.write(0xA0040000, b"\x5a" * 256, pflash_sectors=[0xA0040000])
        assert False, "locked PFLASH program should fail"
    except se.EngineError:
        pass
    # unlock, then write named sector
    s.unlock(0xE1987A4C, 0xFB605D4C)
    s.write(0xA0040000, b"\x5a" * 256, pflash_sectors=[0xA0040000])
    assert s.verify(0xA0040000, b"\x5a" * 256).ok


def test_pflash_write_without_sectors_errors():
    s = se.Session(MockLoader(unlocked=True))
    try:
        s.write(0xA0040000, b"\x00" * 256)         # no --erase-sectors
        assert False
    except se.EngineError as e:
        assert "sector map" in str(e)


def test_partial_page_padding():
    mock = MockLoader()
    s = se.Session(mock)
    data = b"\xAB" * 300                            # 1 full + 1 partial page
    s.write(0xAFE00000, data, pad=0xFF)
    back = s.read(0xAFE00000, 512)
    assert back[:300] == data
    assert back[300:512] == b"\xFF" * 212


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = sum(_run(f) for f in fns)
    print(f"\n{ok}/{len(fns)} passed")
    sys.exit(0 if ok == len(fns) else 1)
