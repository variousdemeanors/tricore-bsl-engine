# TC1767 BSL Engine — Implementation Guide

A complete, platform-agnostic reference for implementing a native-CAN-BSL flash
engine on Infineon TriCore **TC1767 (AUDO-F)**. Written for someone with no prior
context. All values are facts about the silicon/protocol; adapt the *code* to your platform.

---

## 1. Concept & flow

The TC1767 BootROM contains a **CAN bootstrap loader**. When the chip is reset with its boot
pins strapped for CAN-BSL, the ROM listens on CAN for an init frame, accepts a small program
into on-chip scratchpad RAM (**SPRAM @ `0xD4000000`**), and jumps to it. That program — the
**loader** in `loader/` — then does the actual flash work and talks a simple block protocol back
to your host. Two parties:

- **Host** (your platform: PC/Pi/MCU + CAN controller): drives the whole session.
- **Loader** (runs on the TC1767): executes read/erase/program on command.

End-to-end session:
```
reset chip (boot-strapped) ─► host floods INIT on CAN ─► ROM ACKs
  ─► host streams loader frames into SPRAM ─► ROM jumps to 0xD4000000
  ─► loader runs ─► host sends block commands ─► loader reads/erases/programs & replies
```

---

## 2. Native CAN-BSL entry (BootROM protocol — fixed by silicon)

All multi-byte fields little-endian. The host must be an active CAN node at the target baud
(bench-proven **500 kbit/s**; the ROM auto-bauds from your init frame).

**INIT frame** — send repeatedly ("flood") on CAN id `0x000`, DLC 8, until the ROM answers
(the ROM only listens in a short window right after reset, so flood while power-cycling):
```
55 55 | ACKID(LE16) | DMSGC(LE16) | DMSGID(LE16)
```
- `ACKID`, `DMSGID` are 16-bit values; the ROM maps each to an 11-bit CAN id by:
  `id = (value & 0x1FFF) >> 2`.  Using `ACKID=0x4020`→ack on `0x008`, `DMSGID=0x4000`→data on
  `0x000` reproduces the known-good setup.
- `DMSGC` = number of 8-byte loader frames you will send (e.g. a 2020-byte loader → ceil/8 =
  253 frames → `DMSGC=0x00FD`). Variable; not fixed at 640.

**ACK frame** (ROM → host, on the ACKID→id, e.g. `0x008`, DLC 4):
`[bit-timing-reg lo][hi][ACKID lo][ACKID hi]` — e.g. `40 3E 20 40`. Seeing it = ROM is in BSL.

**Loader upload**: immediately after the ACK, send exactly `DMSGC` frames of 8 raw loader bytes
each on the DMSGID→id (`0x000`). Pace ~1 ms/frame (the ROM's receive object is single-buffered).
The ROM copies them to `0xD4000000` and **auto-jumps** there — no "execute" command.

---

## 3. Loader command protocol (this engine's loader — customizable)

Once the loader runs, the host drives it with fixed-size **blocks** split into 8-byte CAN frames
(host→loader on `0x000`, loader→host on `0x008`). Checksum = XOR of all block bytes **except**
the leading type byte and the trailing checksum byte.

- **Header block (16 B = 2 frames):** `[0x00][mode][addr LE32][len LE32][pad…][xor]`
- **Data block (264 B = 33 frames):** `[0x01][verifyflag][256 payload][5 pad][xor]`
- **EOT block (16 B):** `[0x02][zeros][xor]`
- **Status (loader→host, 1 frame):** `0x55`=ACK; errors `0xFE` bad mode, `0xFD` bad checksum,
  `0xFC` bad range, `0xFB` erase, `0xFA` program, `0xF9` verify, `0xF8` protection.

**Modes:** `0x07` read · `0x04` erase sector · `0x00` program 256 B page (Data block follows) ·
`0x06` protect/unprotect · `0x3E` keep-alive (replies `DE AD BE EF D0 0D BA AD`).

Read: send Header(mode 0x07, addr, len) → loader ACKs → streams `ceil(len/256)` Data blocks →
EOT. Program: Header(0x00,addr,256) + Data block → loader programs + read-back-verifies → ACK.

---

## 4. Memory map (TC1767)

| Region | Range | Notes |
|---|---|---|
| PFLASH (program) | `0xA0000000` – `0xA01FFFFF` (2 MB) | password-gated for read/write via BSL |
| DFLASH "EEPROM" | `0xAFE00000`–`0xAFE07FFF` + `0xAFE10000`–`0xAFE17FFF` (2×32 KB) | **not protectable — passwordless** |
| OTP identity/password | `0xA0014000` – `0xA0017FFF` | one-time-programmable; chip-ID + BSL password; never writable |
| SPRAM (loader runs here) | `0xD4000000`, loader window `0x1400` (5120 B) | your loader + its stack/CSA must fit |
| LDRAM | `0xD0000000` | alternative stack/CSA location |

---

## 5. Password model

- **DFLASH/EEPROM read AND write need no password** over BSL. Backup/restore of the 64 KB EEPROM
  is universal and dongle-free.
- **PFLASH read/write is password-gated.** Unlock by sending a protect command (loader mode 0x06)
  carrying `AF 00 <mode> 00 <8-byte key>` to the flash Command Sequence Interface — `mode 0x08` =
  disable read-protection, `0x05` = disable write-protection. Key is the flash controller's own
  value, **per-chip**, MSB-first on the wire. Vendor-tool `.pwd` files are an *encoded* form the
  vendor's dongle transforms into this key; obtaining it per chip is out of scope for this engine.
- The password lives in the **OTP** region, which every write skips → it is immutable and
  chip-locked. (This is why cloning an ECU = cloning its EEPROM, not its PFLASH password.)

---

## 6. Loader internals (what the target code must do at startup)

When the ROM jumps to `0xD4000000` the chip is in a hostile state; the loader's startup
(`loader/crt0.S`) must, before anything else:
1. **Reset the clock to Prescaler Mode** — else the clock is in PLL-freerunning mode, a different
   frequency than the CAN baud was calibrated for, and the loader's CAN transmits at the wrong
   baud (silent). Writes: `0xF000051E = 0x00`, `0xF0000518 = 0x01`.
2. **Disable the watchdog** (`WDTCON0=0xF00005F0`, `WDTCON1=0xF00005F4`) or the chip resets.
3. **Set ENDINIT**, set up **stack pointers + CSA** (TriCore context-save list) before any C call.

**CAN layer** (`loader/main.c` + `loader/tc1767_regs.h`): the loader inherits the ROM's two
message objects — **MO0 = receive, MO1 = transmit** — at MultiCAN base **`0xF0005000`** (MO *n* at
`base + n*0x20`; `MODATAL` `+0x10`, `MODATAH` `+0x14`, `MOCTR/MOSTAT` `+0x1C`, `MOFCR` `+0x00`).
Transmit = write `MODATAL/H`, set `MOFCR = 0x08000000` (DLC 8), kick `MOCTR = 0x0F200000`.
Receive = poll `MOSTAT & 0x08` (NEWDAT), read `MODATAL/H`, clear with `MOCTR = 0x00A00008`.
*(Base `0xF0005000` is the AUDO-F value — do not use `0xF0004600`, which is AUDO-NG/TC1796.)*

The flash operations (erase/program/protect) go through the TC1767 flash **Command Sequence
Interface** — see `loader/flash.c`/`flash.h` for the CSI offsets and sequences.

---

## 7. Porting guide

**Host side (any platform/language).** You need: an active CAN interface at the target baud, and
the ability to send/receive raw 8-byte frames on ids `0x000`/`0x008`. Implement:
1. INIT flood + ACK detection (§2).
2. Loader upload (stream your built `loader.bin`, paced).
3. Block encode/decode (§3) + the read/erase/program/keep-alive drivers.
A SocketCAN example host (Python) lives in `host-reference/`. The protocol is identical whether
your host is a PC, a Raspberry Pi (MCP2515 or gs_usb), or an MCU with a CAN controller.

**Target side (the loader).** Build `loader/` with the TriCore GCC toolchain
(`loader/TOOLCHAIN.md`): `make TRICORE_PREFIX=tricore-elf- MCPU=-mcpu=tc1767` → `canloader.bin`
(must fit the 5120 B SPRAM window — the linker asserts this). You generally won't change the
loader unless you add commands.

**Per-ECU customization.** The engine is chip-level, so the only per-ECU work is:
- **Boot-strap points** — where CNF1/BOOT (and any series resistor) attach on *that* board, to
  put the chip in CAN-BSL at reset. This is physical and board-specific (keep a catalog).
- **PFLASH password** — only if you need PFLASH (not EEPROM) read/write on a locked chip.

**Bring-up checklist (bisect failures in this order):**
1. INIT flood → do you get the ACK on `0x008`? (No → straps/power/baud/active-CAN.)
2. Upload → all frames ACKed? (The ROM hardware-ACKs each; no ACK → bus/termination.)
3. Keep-alive (mode 0x3E) → `DE AD BE EF…` back? (No → loader startup: clock-reset, WDT, CAN base.)
4. Read a few bytes of DFLASH → compare to a known dump.

---

## 8. Minimal "hello" sequence (pseudocode)
```
bring CAN up @500k, active
loop: send INIT(55 55 20 40 <DMSGC> 00 40) until rx(0x008) starts 0x40     # ROM ack
for frame in loader_bin_frames: send(0x000, frame); sleep(1ms)              # upload
sleep(700ms)                                                                # loader self-starts
send Header(mode=0x3E) as 2 frames on 0x000                                 # keep-alive
expect rx(0x008) == DE AD BE EF D0 0D BA AD                                 # loader alive
# then: Header(mode=0x07, addr=0xAFE00000, len=0x8000) → collect Data blocks → EOT  (EEPROM read)
```
