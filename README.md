# tricore-bsl-engine

A portable, platform-agnostic **reference engine** for reading, backing up, and
(emergency-) restoring flash on **Infineon TriCore TC1767 (AUDO-F)** ECUs over the chip's
**native CAN bootstrap loader (BSL)** — no vendor tool, no dongle.

This repo is a **framework / starting point**: a self-contained reference you can port to any
host platform (PC, Raspberry Pi, ESP32, STM32, …) and customize for any TC1767-based ECU. It
assumes **zero prior knowledge** of the authors' other work.

## What's here
| Path | What it is |
|---|---|
| `docs/IMPLEMENTATION_GUIDE.md` | **Start here.** The complete engine reference: BSL entry protocol, loader command protocol, memory map, password model, loader internals, and a step-by-step porting guide. |
| `docs/HARDWARE.md` | Hardware requirements & wiring: CAN transceiver, boot straps, power, grounding, bit timing. |
| `docs/REFERENCES.md` | Pointers to the authoritative Infineon documents (AP32132, TC1767 User Manual/datasheet). Not redistributed here — get them from Infineon. |
| `docs/ROADMAP.md` | Scope over time: the real near-term (TC1767 BSL, passwordless EEPROM) vs. **theoretical/unproven** future (Module-71 GPT pwd extraction, broader TriCore-chip support). |
| `loader/` | The **target-side loader** (TriCore C + asm): uploaded into chip SPRAM and run; implements read / erase / program / protect over a simple block protocol, over **either MultiCAN or ASC0 UART** (`loader/asc/`) — same command logic, `make` vs `make asc`. Build with the TriCore GCC toolchain (`loader/TOOLCHAIN.md`). |
| `host-reference/` | A minimal, language-neutral reference for the **host side** (what the controlling device must send/receive). |

## The idea in one paragraph
The TC1767 BootROM has a built-in CAN bootstrap loader. Strap the chip's boot pins, power it,
and flood a small init frame; the ROM acks, you stream a tiny loader into on-chip SPRAM, and the
ROM jumps to it. That loader (this repo's `loader/`) then speaks a simple block protocol, over
either CAN or a plain UART, to read/erase/program the chip's flash. Because this lives in the
BootROM, it is **chip-level** —
the same engine works on *any* TC1767 ECU regardless of manufacturer or firmware. EEPROM/DFLASH
is unprotected (passwordless read **and** write); PFLASH read/write needs that chip's password.

## Status / provenance
Built from our own bench effort on Kefico MED17.9.8 (TC1767). On real silicon: BSL entry, loader
upload, and ROM-jump-to-loader are proven; the loader's CAN I/O is aligned to Infineon's official
AP32132 CANLoader (correct MultiCAN base `0xF0005000`, clock-reset, WDT, MOFCR). The flash **write**
path is proven too — both **DFLASH** (EEPROM, passwordless) and **PFLASH** (needs a host-supplied
write-unlock key) did a clean erase→program→verify round-trip, including a full-flash reflash of a
read+write-protected unit. All register constants in this revision are confirmed on real TC1767
silicon (no `TODO(bench)` markers remain) — but that is this engine's bench, on this chip;
re-verify before trusting a different TC1767-family part.

**Two transports, both proven, same command logic:** MultiCAN (the default build) first, then
**ASC0 UART** (`make asc`) — identical BSL entry, loader upload, read, and the full write path,
confirmed independently over serial as well as CAN.

## Safety
Writing flash on a live ECU can **brick** it. The write path is proven on one bench TC1767
(Kefico MED17.9.8) — porting to a different TC1767-family part, PCB revision, or toolchain is
new ground and should be re-verified before you trust it. Use only on hardware you own or are
authorized to service, keep a verified full backup first, and expect no warranty of any kind.

## Contributing / porting reports
This is a reference engine, bench-confirmed on one TC1767 (Kefico MED17.9.8), over both CAN and
ASC. **If you run this on a TC1767 ECU** — same family or different — please
[open an issue](../../issues) or a [discussion](../../discussions) with:

- the ECU / chip you tried it on,
- which transport (CAN or ASC), and
- what worked, and what you had to change.

Independent confirmations on other TC1767-family parts are the fastest way to turn "proven on
one bench" into "proven broadly." No vehicle-specific secrets, keys, or captures in reports,
please — see `NOTICE` for the scope boundary.

## License & credits
Original work, released under the **MIT License** (see `LICENSE` and `NOTICE`). This is an
independent TC1767 implementation built from our own reverse engineering and the Infineon TC1767
documentation; it contains **no third-party source code**.

- **Prior art / independent confirmation:** `bri3d/TC1791_CAN_BSL` (the related TC1791 / AUDO-MAX
  CAN BSL) corroborates the shared AUDO command-sequence values; `fastboatster/TC1796_CAN_bootloader`
  (the related TC1796 / AUDO-NG CAN BSL) is a structure reference for the startup code and CAN
  register layout. Both credited with thanks; no code is copied from either.
- **Infineon** AP32132 and the TC1767 User Manual are **referenced, not redistributed**
  (see `docs/REFERENCES.md`) — obtain them from Infineon under their terms.
- Requires the operator to supply their own chip's unlock keys; obtaining them, and anything
  beyond the proven read/write/protect-disable primitives in this repo, is out of scope
  (see `NOTICE`).
