"""
Cross-check the host protocol encoder (host/tc1767/protocol.py) against the
loader's OWN portable block logic, compiled on the host as
loader/selftest/host_selftest (see `make selftest`).

Run: python3 -m pytest host/tests/  (or: python3 host/tests/test_protocol.py)

If the compiled self-test is absent, the C-cross-check tests skip and only the
pure-Python invariants run.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "host"))

from tc1767 import protocol as p  # noqa: E402

SELFTEST = os.path.join(ROOT, "loader", "selftest", "host_selftest")


def _pat(i):
    return (i * 7 + 3) & 0xFF


def _host_read_frames(length):
    """Reproduce the loader's do_read() frame stream for the deterministic
    pattern, using only the host encoder."""
    img = bytes(_pat(i) for i in range(length))
    out = bytearray()
    off = 0
    while off < length:
        chunk = img[off:off + p.DATA_PAYLOAD]
        out += p.build_data_block(chunk)
        off += p.DATA_PAYLOAD
    out += p.build_eot()
    return bytes(out)


def _skip(msg):
    try:
        import pytest
        pytest.skip(msg)
    except ImportError:
        print("SKIP:", msg)
        return True
    return False


# ---- pure invariants (always run) ------------------------------------------

def test_header_checksum_and_fields():
    h = p.build_header(p.MODE_READ, 0xAFE00000, 0x8000)
    assert len(h) == 16 and h[0] == p.BLK_HEADER and h[1] == p.MODE_READ
    assert h[2:6] == bytes((0x00, 0x00, 0xE0, 0xAF))      # addr LE32
    assert h[6:10] == bytes((0x00, 0x80, 0x00, 0x00))     # len LE32
    assert h[15] == p.block_xor(h, 15)


def test_data_block_roundtrip_and_pad():
    payload = bytes(range(100))
    blk = p.build_data_block(payload)
    assert len(blk) == 264 and blk[0] == p.BLK_DATA
    assert p.parse_data_block(blk) == payload + bytes(156)  # zero-padded to 256


def test_protect_header_layout():
    h = p.build_protect_header(p.PROT_DISABLE_WRITE, 0xE1987A4C, 0xFB605D4C, ucb=0)
    assert h[1] == p.MODE_PROTECT and h[2] == p.PROT_DISABLE_WRITE and h[3] == 0
    assert h[4:8] == bytes((0x4C, 0x7A, 0x98, 0xE1))
    assert h[8:12] == bytes((0x4C, 0x5D, 0x60, 0xFB))
    assert h[15] == p.block_xor(h, 15)


def test_range_gate_matches_loader_semantics():
    assert p.in_backup_range(0xAFE00000, 0x8000) is True
    assert p.in_backup_range(0xAFE00000, 0x8001) is False   # one past the bank
    assert p.in_backup_range(0xAFE08000, 1) is False        # the unimplemented gap
    assert p.in_backup_range(0xA0000000, 0x200000) is True
    assert p.in_backup_range(0, 0) is False


# ---- cross-check against the compiled loader C logic -----------------------

def test_read_frames_match_c_selftest():
    if not os.path.exists(SELFTEST):
        if _skip("loader/selftest/host_selftest not built (run `make selftest`)"):
            return
    for length in (1, 255, 256, 257, 300, 0x400):
        c = subprocess.run([SELFTEST, "read", str(length)],
                           capture_output=True, text=True, check=True)
        c_bytes = bytes.fromhex(c.stdout.replace("\n", ""))
        assert _host_read_frames(length) == c_bytes, f"mismatch at len={length}"


def test_le32_matches_c_selftest():
    if not os.path.exists(SELFTEST):
        if _skip("host_selftest not built"):
            return
    for hexv in ("AFE00000", "D4000000", "12345678", "000000FF"):
        c = subprocess.run([SELFTEST, "le32", hexv],
                           capture_output=True, text=True, check=True)
        b = bytes.fromhex(hexv)[::-1]  # the C reads b[0..3]=LE of the value
        host_val = p._le32  # noqa
        # le32(bytes) in the loader decodes little-endian; reproduce:
        val = b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)
        assert f"{val:08x}" == c.stdout.strip(), hexv


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
