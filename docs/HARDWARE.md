# Hardware requirements & wiring

The engine needs only a few low-cost signals. The split is deliberate: **you (the host) provide
logic-level signals; the bench provides power.**

## What the host must provide
- **A CAN interface, active, at the target baud** (bench-proven 500 kbit/s). Any of: a PC/Pi CAN
  adapter (MCP2515 SPI HAT, gs_usb/candleLight, SocketCAN), or an MCU with a CAN controller +
  transceiver. It must be able to send/receive raw standard-id frames and be an *active* node
  (not listen-only) so it transmits and the ECU ACKs it.
- **Boot-strap drive** for CAN-BSL entry: the TC1767 `CNF1`/`BOOT` config pins must be held at the
  correct levels at reset. These are **logic-level, ~zero current** — a GPIO (level-shifted to the
  pin's voltage, typically 3.3 V or 5 V — make it selectable) or a simple resistor strap suffices.
  Some board variants need a series resistor (e.g. a 1 kΩ on certain auto-trans MEDG units).
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
| CNF1 / BOOT (+ series R if needed) | host → ECU | config pins, sampled at reset; board-specific location |
| GND | common | mandatory |
| 12 V | PSU → ECU | bench supply, not the host |

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
