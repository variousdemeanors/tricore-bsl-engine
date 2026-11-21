# Hardware requirements & wiring

The engine needs only a few low-cost signals. The split is deliberate: **you (the host) provide
logic-level signals; the bench provides power.**

## What the host must provide
Pick one transport; the loader's command logic is identical either way (`make` vs `make asc`):
- **CAN interface, active, at the target baud** (bench-proven 500 kbit/s). Any of: a PC/Pi CAN
  adapter (MCP2515 SPI HAT, gs_usb/candleLight, SocketCAN), or an MCU with a CAN controller +
  transceiver. It must be able to send/receive raw standard-id frames and be an *active* node
  (not listen-only) so it transmits and the ECU ACKs it.
- **or a plain UART** to the TC1767's ASC0 pins (`loader/asc/asc_io.c`), at whatever baud the
  BootROM autobauds to on your part. Point-to-point TX/RX is enough — no CAN controller needed.
  Bench-proven at a bitrate near 250 kbaud; the loader switches baud after upload (see
  `asc_io.c`'s `asc0_init`). If your TX physically loops back into your own RX (e.g. a shared
  half-duplex pair), the loader already discards its own echo — no host-side change needed.
- **Boot-strap drive** for CAN-BSL entry: the TC1767 `CNF1`/`BOOT` config pins must be held at the
  correct levels at reset. These are **logic-level, ~zero current** — a GPIO (level-shifted to the
  pin's voltage) or simple resistor straps suffice. For the MED17.9.8 / MEDG17.9.8 units the
  verified straps are **CNF1 HIGH** (3.3 V via a current-limiting resistor) and **both BOOT pads
  LOW** (to GND through a 1 kΩ, which the two pads may share) — full table in
  "[MED17.9.8 & MEDG17.9.8 — BSL strap & signal connections](#med1798--medg1798--bsl-strap--signal-connections)" below.
- **A way to reset/power-cycle the ECU on cue** (the BootROM only listens for BSL right after
  reset). Manual switch is fine; or a GPIO-driven MOSFET on the ignition/enable line.

## What the bench provides
- **ECU main power (12 V) from a proper bench supply.** An ECU draws amps; do **not** try to
  source this from a Pi/MCU. The host only provides signals + a common ground.
- **Common ground** between the host, any strap driver, and the ECU/PSU. (Omitting common ground
  is a classic cause of "nothing works".)

## Signals summary (per ECU board)
| Signal | Direction | Notes |
|---|---|---|
| CAN-H / CAN-L | host ↔ ECU | to the ECU's BSL CAN pins; 120 Ω termination at both ends |
| ASC0 TX/RX *(alternative to CAN)* | host ↔ ECU | **carried over the same CAN-H / CAN-L conductors** (half-duplex serial, not separate pins); the loader discards its own echo (see `loader/asc/asc_io.c`) |
| CNF1 / BOOT | host → ECU | config straps, sampled at reset; board-specific pad location |
| GND | common | mandatory |
| 12 V | PSU → ECU | bench supply, not the host |

## MED17.9.8 & MEDG17.9.8 — BSL strap & signal connections

These two ECUs are **electrically identical** for native CAN-BSL entry; only the physical pad
locations differ (see the per-ECU pad notes below). BSL access is **case-open** (Module 53).
Values below are verified for these units.

| Signal | Connection at the ECU | Level / value at reset | Notes |
|---|---|---|---|
| CAN-H | host CAN-H ↔ ECU CAN-H | — | BSL CAN pair, 120 Ω at both ends; host active, 500 kbit/s |
| CAN-L | host CAN-L ↔ ECU CAN-L | — | same pair as CAN-H |
| ASC0 TX/RX | **over CAN-H / CAN-L** | — | serial alternative runs on the CAN pair (half-duplex); no separate serial pins |
| K-line | not used | — | this engine uses CAN, or ASC0 over the CAN pair; no K-line |
| CNF1 | 3.3 V logic through a current-limiting series resistor | **HIGH**, 2.3–3.0 V | config pin; held high selects the CAN-BSL boot path at reset |
| BOOT (both straps) | to **GND through 1 kΩ** | **LOW** (pulled to ground) | the two BOOT pads may share a **single 1 kΩ** at its ground connection |
| GND | common host ↔ strap driver ↔ ECU/PSU | 0 V | mandatory common ground |
| 12 V | bench PSU → ECU | 12 V | ECU draws amps — bench supply, never the host |

**Routing (both ECUs):** keep every strap lead **as short as possible** — extra wire adds series
resistance to the straps and picks up interference, both of which can keep the chip out of (or
unreliable in) CAN-BSL at reset.

### MED17.9.8 — pad locations
CNF1 and the two BOOT pads are at their board-specific locations on the MED17.9.8 PCB.
*(CNF1 / BOOT pad-location photo to be added.)*

### MEDG17.9.8 — pad locations
Same strap electricals as MED17.9.8 above; CNF1 and the two BOOT pads are at the MEDG17.9.8
board's own locations. *(CNF1 / BOOT pad-location photo to be added.)*

## Entry timing
Start the INIT flood, then power-cycle the ECU; the ROM catches the flood in its post-reset BSL
window. If the host's CAN controller has no one to ACK its floods before the ECU is alive, it may
error-cycle — use a controller auto-restart (SocketCAN `restart-ms`) or leave another node on the
bus for termination/ACK.

## Notes
- **Module 53 (native CAN BSL)** generally requires opening the ECU case to reach the strap points.
- **GPT boot (Module 71)** is a different, connector-level path (no case) but is vendor-tool gated
  in practice and out of scope for this engine.
- The engine is chip-level, so the *electrical* requirements are the same across TC1767 ECUs — only
  the physical strap-point **locations** differ per board.
