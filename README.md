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
| `loader/` | The **target-side loader** (TriCore C + asm): uploaded into chip SPRAM and run; implements read / erase / program / protect over a simple block protocol. Build with the TriCore GCC toolchain (`loader/TOOLCHAIN.md`). |
| `host-reference/` | A minimal, language-neutral reference for the **host side** (what the controlling device must send/receive). |

## The idea in one paragraph
The TC1767 BootROM has a built-in CAN bootstrap loader. Strap the chip's boot pins, power it,
and flood a small init frame; the ROM acks, you stream a tiny loader into on-chip SPRAM, and the
ROM jumps to it. That loader (this repo's `loader/`) then speaks a simple block protocol over CAN
to read/erase/program the chip's flash. Because this lives in the BootROM, it is **chip-level** —
the same engine works on *any* TC1767 ECU regardless of manufacturer or firmware. EEPROM/DFLASH
is unprotected (passwordless read **and** write); PFLASH read/write needs that chip's password.

## Status / provenance
Derived from a working bench effort on Kefico MED17.9.8 (TC1767). On real silicon: BSL entry,
loader upload, and ROM-jump-to-loader are proven; the loader's CAN I/O was aligned to Infineon's
official AP32132 CANLoader (correct MultiCAN base `0xF0005000`, clock-reset, WDT, MOFCR) and is at
final bench bring-up. Treat register pokes marked `TODO(bench)` as to-confirm on your part.

## Legal
For use on hardware you own or are authorized to service. The authoritative Infineon documents
are **referenced, not included** (see `docs/REFERENCES.md`) — obtain them from Infineon under
their terms. The loader code here is original work.
