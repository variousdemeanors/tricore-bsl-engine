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

import errno
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


_CAN_RAW_RECV_OWN_MSGS = 4   # <linux/can/raw.h>; not always exposed by socket


class CanTransport:
    def __init__(self, interface="can0", tx_id=0x000, rx_id=0x008,
                 frame_pace=0.001, recover=False):
        self.interface = interface
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.frame_pace = frame_pace
        self.recover = recover        # software bus-off recovery for adapters
        self.sock = None              # without restart-ms (needs sudo ip link)

    def _bus_off_recover(self):
        """Emulate restart-ms on adapters that lack it: down/up the interface so
        the flood survives the ECU's boot (while it isn't ACKing yet, the flood
        gets no ACK and the controller heads to bus-off). Needs passwordless
        `sudo ip link`. The bound socket survives the link flap."""
        import subprocess
        for args in (["down"], ["up"]):
            subprocess.run(["sudo", "-n", "ip", "link", "set", self.interface] + args,
                           capture_output=True)
        time.sleep(0.005)   # let the link settle before resuming the flood

    # -- lifecycle ----------------------------------------------------------
    def open(self):
        try:
            s = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            # Receive our OWN frames echoed back when they actually reach the bus
            # (i.e. were ACKed) -- the gated-flood entry uses this own-echo as
            # proof-of-transmit. Filter to our two ids so the echoes (tx_id) and
            # the loader replies (rx_id) both arrive and nothing else does.
            try:
                s.setsockopt(socket.SOL_CAN_RAW, _CAN_RAW_RECV_OWN_MSGS, 1)
            except OSError:
                pass
            flt = struct.pack("=IIII",
                              self.tx_id, socket.CAN_SFF_MASK,
                              self.rx_id, socket.CAN_SFF_MASK)
            s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER, flt)
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

    # -- gated-entry primitives (own-echo = proof a frame hit the bus) ------
    _SOFT_TX_ERRNOS = (errno.ENOBUFS, errno.EAGAIN, errno.EWOULDBLOCK,
                       errno.ENETDOWN, errno.ENODEV)

    def _send_nowait(self, data: bytes):
        payload = data.ljust(8, b"\x00")[:8]
        try:
            self.sock.send(struct.pack(_CAN_FMT, self.tx_id, 8, payload))
        except OSError as e:
            # queue full / retrying, or the link is mid bus-off recovery (down):
            # drop this attempt, the flood loop will re-send.
            if e.errno not in self._SOFT_TX_ERRNOS:
                raise

    def _poll_event(self, timeout):
        """-> ('own', data) for one of our own frames echoed off the bus,
        ('rx', data) for a loader/BootROM reply, or None on timeout."""
        try:
            if not select.select([self.sock], [], [], timeout)[0]:
                return None
            raw = self.sock.recv(_CAN_FRAME_SZ)
        except OSError:
            return None   # link flapping during bus-off recovery
        cid, dlc = struct.unpack("=IB3x", raw[:8])
        cid &= 0x1FFFFFFF
        data = raw[8:8 + dlc].ljust(8, b"\x00")
        if cid == self.tx_id:
            return ("own", data)
        if cid == self.rx_id:
            return ("rx", data)
        return None

    def _send_confirmed(self, data: bytes, timeout=0.5):
        """Send one frame and block until its own echo proves it reached the bus
        (was ACKed), so the next frame never piles up behind an unsent one."""
        self._send_nowait(data)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            ev = self._poll_event(max(0.0, end - time.monotonic()))
            if ev and ev[0] == "own" and ev[1][:8] == data.ljust(8, b"\x00")[:8]:
                return
        raise TransportError("frame not echoed within timeout (bus not ACKing -- "
                             "ECU powered? strapped? bitrate 500k?)")

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
                         on_wait=None, power=None, power_off_ms=600,
                         power_boot_ms=400):
        """Flood INIT until the BootROM ACKs (first reply byte 0x40), then stream
        the loader into SPRAM.

        With `power` (a power.PinctrlPower): the ECU is reset by the relay and
        brought up READY before flooding -- OFF, then ON, then a short boot delay
        so the BootROM is already in its CAN-BSL listen window. This matters on a
        2-node bus with no restart-ms: if we flood while the ECU is still dead,
        nothing ACKs our frames, the TX queue jams (ENOBUFS) and the controller
        heads to bus-off. Powering up first means the very first init frame is
        ACKed, so no jam. Without `power`, the caller power-cycles by hand during
        the flood (ENOBUFS is tolerated meanwhile).
        """
        frames = [loader_bin[i:i + 8] for i in range(0, len(loader_bin), 8)]
        if frames and len(frames[-1]) < 8:
            frames[-1] = frames[-1].ljust(8, b"\x00")
        dmsgc = len(frames)
        init = b"\x55\x55" + struct.pack("<HHH", ackid, dmsgc, dmsgid)

        have_power = power is not None and getattr(power, "enabled", False)
        if have_power:
            power.off()
            time.sleep(power_off_ms / 1000.0)
        if on_wait:
            on_wait(dmsgc)
        self.drain()
        # Flood-FIRST, then power the ECU on INTO the live flood (the proven
        # sequence): the BootROM's CAN-BSL listen window is right after reset, so
        # the flood must already be on the bus when the ECU comes up. While the
        # ECU is still booting nothing ACKs our init, so without restart-ms the
        # controller bus-offs in milliseconds -- self.recover re-ups the link so
        # the flood survives the ~100-200 ms boot and is live when the ROM listens.
        if have_power:
            power.on()
            # no pre-flood delay: start flooding immediately so it's live as the
            # ECU resets (power_boot_ms kept for callers that want a delay)
            if power_boot_ms:
                time.sleep(power_boot_ms / 1000.0)

        # Gated flood: keep exactly ONE init in flight. Send one, wait for its
        # own-echo (proof it hit the bus = was ACKed) and a short gap, then the
        # next -- clean, paced init frames the BootROM can auto-baud from and
        # reply to, with no TX backlog. An ungated blast overruns the ROM's
        # single receive object; a backlog of inits also lands on the loader-data
        # id after the ack and corrupts the upload.
        ack = None
        ack_wait = 0.003
        recover_after = 0.12          # no echo this long => likely bus-off
        in_flight = False
        last_echo = None
        sent_at = None
        end = time.monotonic() + flood_timeout
        while ack is None:
            now = time.monotonic()
            if now > end:
                raise TransportError(
                    "no BootROM ACK on CAN. Check: boot straps, ECU power/reset, "
                    "500 kbit/s + active (not listen-only), common ground.")
            if not in_flight and (last_echo is None or now - last_echo > ack_wait):
                self._send_nowait(init)
                in_flight = True
                sent_at = now
            # in-flight frame not echoed for a while -> controller is bus-off
            # (ECU not ACKing yet); recover the link and re-arm the flood.
            if in_flight and self.recover and sent_at is not None \
                    and now - sent_at > recover_after:
                self._bus_off_recover()
                in_flight = False
                last_echo = None
                continue
            ev = self._poll_event(0.0005)
            if ev is None:
                continue
            kind, data = ev
            if kind == "own" and data[:2] == init[:2]:
                in_flight = False
                last_echo = time.monotonic()
            elif kind == "rx" and data[0] == 0x40:
                ack = data

        # Drain: no stale init may hit the bus after the ack, or it lands on the
        # loader-data id and corrupts the upload.
        stale = 0
        drain_end = time.monotonic() + max(settle, 0.02 if in_flight else 0.0)
        while time.monotonic() < drain_end:
            ev = self._poll_event(0.01)
            if ev and ev[0] == "own" and ev[1][:2] == init[:2]:
                stale += 1
        if stale:
            raise TransportError(
                f"{stale} init frame(s) reached the bus after the ack -- upload "
                f"would be corrupt (retry entry)")

        for f in frames:                       # each frame confirmed on the bus
            self._send_confirmed(f)
            if self.frame_pace:                # pace uploads for adapters whose
                time.sleep(self.frame_pace)    # own-echo is decoupled from the ACK
        time.sleep(run_delay)                  # loader self-starts


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
