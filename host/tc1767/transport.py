"""
Transport layer for the TC1767 BSL engine.

Two transports, matching the loader's two builds:
  * CanTransport  -- MultiCAN, SocketCAN raw frames (loader: `make`,  canloader.bin)
  * AscTransport  -- ASC0 UART via pyserial         (loader: `make asc`, ascloader.bin)

Both expose the same small surface the session layer uses:
  send_block(bytes)                 send a fully-built 16/264-byte block
  read_status(timeout) -> int       one loader status byte (0x55 / 0xFx)
  read_frames(n, timeout) -> bytes  read n bytes (n a multiple of 8)
  enter_and_upload(loader_bin, ...) BootROM BSL entry + loader upload

CAN carries each 8-byte "frame" as one standard-id CAN frame; a status is a frame
whose data[0] is the code. ASC is a raw byte stream; a status is a single byte.
"""

from __future__ import annotations

import select
import socket
import struct
import time

from . import protocol as p


class TransportError(RuntimeError):
    pass


# ============================================================ CAN (SocketCAN)

# classic CAN frame: can_id (u32), dlc (u8), 3 pad, data[8]
_CAN_FMT = "=IB3x8s"
_CAN_FRAME_SZ = 16


class CanTransport:
    def __init__(self, interface="can0", tx_id=0x000, rx_id=0x008,
                 frame_pace=0.001):
        self.interface = interface
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.frame_pace = frame_pace
        self.sock = None

    # -- lifecycle ----------------------------------------------------------
    def open(self):
        try:
            s = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            s.bind((self.interface,))
        except OSError as e:
            raise TransportError(
                f"cannot open CAN interface '{self.interface}': {e}. "
                f"Is it up? Try: sudo ip link set {self.interface} up type can bitrate 500000"
            ) from e
        s.setblocking(False)
        self.sock = s
        return self

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *a):
        self.close()

    # -- raw frames ---------------------------------------------------------
    def _send_frame(self, data: bytes):
        payload = data.ljust(8, b"\x00")[:8]
        self.sock.send(struct.pack(_CAN_FMT, self.tx_id, 8, payload))

    def _recv_frame(self, timeout):
        """Return the 8-byte data of the next frame on rx_id, or None on timeout."""
        end = time.monotonic() + timeout
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return None
            if not select.select([self.sock], [], [], remaining)[0]:
                return None
            raw = self.sock.recv(_CAN_FRAME_SZ)
            cid, dlc = struct.unpack("=IB3x", raw[:8])
            if (cid & 0x1FFFFFFF) == self.rx_id:
                return raw[8:8 + dlc].ljust(8, b"\x00")

    # -- session surface ----------------------------------------------------
    def send_block(self, block: bytes):
        for i in range(0, len(block), 8):
            self._send_frame(block[i:i + 8])
            if self.frame_pace:
                time.sleep(self.frame_pace)

    def read_status(self, timeout=3.0) -> int:
        fr = self._recv_frame(timeout)
        if fr is None:
            raise TransportError("timed out waiting for loader status frame")
        return fr[0]

    def read_frames(self, nbytes, timeout=3.0) -> bytes:
        if nbytes % 8:
            raise ValueError("nbytes must be a multiple of 8")
        out = bytearray()
        while len(out) < nbytes:
            fr = self._recv_frame(timeout)
            if fr is None:
                raise TransportError(
                    f"timed out reading frames ({len(out)}/{nbytes} B)")
            out += fr
        return bytes(out[:nbytes])

    def drain(self):
        while self._recv_frame(0.0) is not None:
            pass

    # -- BootROM BSL entry --------------------------------------------------
    def enter_and_upload(self, loader_bin: bytes, ackid=0x4020, dmsgid=0x4000,
                         flood_timeout=60.0, settle=0.15, run_delay=0.7,
                         on_wait=None):
        """Flood INIT until the BootROM ACKs (first reply byte 0x40), then stream
        the loader into SPRAM. The caller power-cycles the ECU during the flood.
        """
        frames = [loader_bin[i:i + 8] for i in range(0, len(loader_bin), 8)]
        if frames and len(frames[-1]) < 8:
            frames[-1] = frames[-1].ljust(8, b"\x00")
        dmsgc = len(frames)
        init = b"\x55\x55" + struct.pack("<HHH", ackid, dmsgc, dmsgid)

        if on_wait:
            on_wait(dmsgc)
        self.drain()
        end = time.monotonic() + flood_timeout
        while True:
            self._send_frame(init)
            fr = self._recv_frame(0.002)
            if fr is not None and fr[0] == 0x40:
                break
            if time.monotonic() > end:
                raise TransportError(
                    "no BootROM ACK on CAN. Check: boot straps, ECU power-cycle "
                    "timing, 500 kbit/s + active (not listen-only), common ground.")
        time.sleep(settle)
        for f in frames:
            self._send_frame(f)
            time.sleep(self.frame_pace)
        time.sleep(run_delay)   # loader self-starts


# ================================================================ ASC (UART)

class AscTransport:
    """TC1767 ASC0 serial transport.

    NOTE on scope: the loader's *command phase* over ASC (and its documented
    0xA5 -> switch-baud -> 0x55 sync handshake) is implemented here. The BootROM
    *serial* BSL upload timing is part-specific and is bench-tuned; see connect().
    The CAN transport is the fully host-documented path in this repo.
    """

    def __init__(self, port, upload_baud=19200, cmd_baud=250000,
                 byte_pace=0.0):
        self.port = port
        self.upload_baud = upload_baud
        self.cmd_baud = cmd_baud
        self.byte_pace = byte_pace
        self.ser = None

    def open(self):
        try:
            import serial  # pyserial
        except ImportError as e:
            raise TransportError(
                "pyserial not installed. Run `./tricore-bsl-engine --setup` "
                "or: pip install pyserial") from e
        try:
            self.ser = serial.Serial(self.port, self.upload_baud, timeout=1)
        except Exception as e:
            raise TransportError(f"cannot open serial port '{self.port}': {e}") from e
        return self

    def close(self):
        if self.ser:
            self.ser.close()
            self.ser = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *a):
        self.close()

    def set_baud(self, baud):
        self.ser.baudrate = baud

    def send_block(self, block: bytes):
        if self.byte_pace:
            for byte in block:
                self.ser.write(bytes((byte,)))
                time.sleep(self.byte_pace)
        else:
            self.ser.write(block)
        self.ser.flush()

    def _read_exact(self, n, timeout):
        self.ser.timeout = timeout
        data = self.ser.read(n)
        if len(data) < n:
            raise TransportError(f"serial read timed out ({len(data)}/{n} B)")
        return data

    def read_status(self, timeout=3.0) -> int:
        return self._read_exact(1, timeout)[0]

    def read_frames(self, nbytes, timeout=3.0) -> bytes:
        return self._read_exact(nbytes, timeout)

    def enter_and_upload(self, loader_bin: bytes, run_delay=0.7, on_wait=None,
                         **_):
        """Stream the ASC loader after an ECU reset, then complete the documented
        baud-switch handshake: loader emits 0xA5 at the upload baud, host switches
        to cmd_baud and sends 0x55, loader replies 0x55 (ACK) from main()."""
        if on_wait:
            on_wait(len(loader_bin) // 8)
        self.ser.reset_input_buffer()
        self.ser.write(loader_bin)
        self.ser.flush()
        # Wait for the loader's baud-switch announcement (0xA5).
        self.ser.timeout = max(run_delay, 2.0)
        while True:
            b = self.ser.read(1)
            if not b:
                raise TransportError(
                    "no 0xA5 baud-switch byte from ASC loader after upload "
                    "(serial BootROM entry timing is part-specific/bench-tuned)")
            if b[0] == 0xA5:
                break
        self.set_baud(self.cmd_baud)
        self.ser.write(b"\x55")      # ASC_DATA_SYNC
        self.ser.flush()
        ack = self.read_status(timeout=3.0)
        if ack != p.RESP_ACK:
            raise TransportError(
                f"ASC loader did not ACK after baud switch (got 0x{ack:02x})")
