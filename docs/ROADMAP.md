# Roadmap

Scope of this engine over time. **Near-term is real; the theoretical section is
aspirational and unproven — do not treat it as shipping or as a commitment.**

## Now / near-term (TC1767 native BSL, CAN or ASC)
- **BSL entry + loader upload + run on TC1767** — proven on real silicon, on two distinct
  bench ECUs, over **both** transports this loader supports: MultiCAN and ASC0 UART
  (`make` vs `make asc`); see README "Status / provenance" for which unit ran which transport.
- **EEPROM / DFLASH erase + program + verify — passwordless, architecturally universal**
  across TC1767 ECUs (DFLASH has no protection mechanism on this chip family at all — no
  vendor tool, no dongle, no per-chip secret). Proven on real silicon on both bench units.
  This is the core deliverable.
- **PFLASH erase + program** — the same mechanism, proven on real silicon on both bench
  units, but requires a one-time **temporary write-unlock (Mode 0x06)** with that chip's
  own unlock key words, supplied by the host. **Obtaining those key words is out of this
  engine's scope** — see `NOTICE`. Without them, a protected chip's PFLASH stays protected;
  DFLASH never needs a key.
- **PFLASH protection is per-chip, not predictable from the part number/variant label.**
  One bench unit's label would normally suggest unprotected PFLASH; it ships protected
  anyway. Check a chip's own FSR, don't assume from its label.
- **Per-ECU enablement** = documenting that board's boot-strap probe points (a catalog entry,
  not new code), because everything else is chip-level.

## Planned
- **Module-71 GPT-boot operations, including TPROT password EXTRACTION.** A connector-level
  (no-case) GPT-gated path that today relies on vendor tooling. This path is already available
  via PCMFlash module 71. I'm currently blocked by the seed/key auth handshake. Not sure if I
  will spend much more time on this specific algorithm/transform as it only takes an extra 10 minutes
  to open the case and apply BSL straps. The GPT0/GPT1 crankshaft/camshaft signals are static on
  Bosch/Kefico MED(G)17.9.8 and should be present BEFORE 12v/IGN is applied.  
- **Support for TriCore parts beyond TC1767.** The approach is chip-level, so much of the wider
  **AUDO family** (e.g. TC1766 / TC1796 / TC1791) — and potentially newer TriCore — should port
  with per-chip work: MultiCAN base + register map, flash CSI/sector map, SCU clock/WDT registers,
  and boot-strap entry. *Each new part needs its register/address set confirmed and a bench
  bring-up.* (Porting trap already learned: AUDO-F MultiCAN base is `0xF0005000`, AUDO-NG is
  `0xF0004600` — bases differ per family.)

## Why these are plausible (but still unproven)
The engine sits on silicon-level BootROM/flash mechanisms shared across the TriCore AUDO line, and
the password/GPT work has partial precedent. "Plausible" ≠ "done" — every item above requires its
own reverse-engineering and on-hardware confirmation before it can be relied on.
