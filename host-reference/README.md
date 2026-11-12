# Host-side reference

The host is whatever device drives the session (PC, Raspberry Pi, MCU). Its only requirements:
an **active CAN interface** at the target baud and the ability to send/receive raw 8-byte
standard-id frames on `0x000` (host→target) and `0x008` (target→host). The protocol is in
`../docs/IMPLEMENTATION_GUIDE.md`; this is a language-neutral skeleton to port.

## Host contract (what you must implement)
1. **Bring CAN up, active, at the target baud** (e.g. 500 kbit/s). Not listen-only.
2. **INIT flood + ACK**: repeatedly send `55 55 | ACKID | DMSGC | DMSGID` on `0x000` until a
   frame whose first byte is `0x40` arrives on `0x008`. `DMSGC` = number of 8-byte loader frames.
3. **Upload**: stream the loader `.bin` as 8-byte frames on `0x000`, ~1 ms apart. The ROM jumps
   to it automatically. Wait ~0.7 s for self-start.
4. **Command**: build/parse blocks (header/data/EOT, XOR checksum excluding type+checksum bytes),
   implement keep-alive (mode `0x3E`), read (`0x07`), erase (`0x04`), program (`0x00`+Data).

## Reference skeleton (Python / SocketCAN — port as needed)
```python
import socket, struct, select, time
CH, TX, RX = "can0", 0x000, 0x008
FMT = "=IB3x8s"   # SocketCAN classic frame: can_id(u32), dlc(u8), 3 pad, data[8]

def open_can():
    s = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    s.bind((CH,)); s.setblocking(False); return s

def send(s, cid, data):            # data: up to 8 bytes
    s.send(struct.pack(FMT, cid, 8, data.ljust(8, b"\\0")[:8]))

def poll(s, timeout):
    if select.select([s], [], [], timeout)[0]:
        fr = s.recv(16); cid, dlc = struct.unpack("=IB3x", fr[:8])
        return cid & 0x1FFFFFFF, fr[8:8+dlc]
    return None, None

def enter_and_upload(s, loader_bin, ackid=0x4020, dmsgid=0x4000):
    frames = [loader_bin[i:i+8] for i in range(0, len(loader_bin), 8)]
    if len(frames[-1]) < 8: frames[-1] = frames[-1].ljust(8, b"\\0")
    init = b"\\x55\\x55" + struct.pack("<HHH", ackid, len(frames), dmsgid)
    t = time.time()                              # flood INIT until ROM acks (power-cycle now)
    while time.time() - t < 60:
        send(s, TX, init)
        cid, d = poll(s, 0.002)
        if cid == RX and d and d[0] == 0x40: break
    else: raise RuntimeError("no BootROM ack")
    time.sleep(0.15)
    for f in frames: send(s, TX, f); time.sleep(0.001)   # upload, paced
    time.sleep(0.7)                              # loader self-starts

def xor(b): 
    c = 0
    for x in b[1:-1]: c ^= x
    return c

def keep_alive(s):                               # mode 0x3E -> expect DE AD BE EF D0 0D BA AD
    hdr = bytes([0x00, 0x3E] + [0]*13 + [0x3E])
    send(s, TX, hdr[:8]); send(s, TX, hdr[8:])
    t = time.time()
    while time.time() - t < 3:
        cid, d = poll(s, 0.05)
        if cid == RX and d == bytes.fromhex("DEADBEEFD00DBAAD"): return True
    return False
# read(addr,len): send 16B header [00,07,addr LE32,len LE32,...,xor] as 2 frames,
#   expect 0x55 ack, then ceil(len/256) 264B data blocks (33 frames each), then EOT.
```

A fuller working version (with read/erase/program drivers and a mock-ECU test suite) exists in
the authors' internal `gammaflash` host (`gammaflash/bsl/`). This skeleton is the portable core.
