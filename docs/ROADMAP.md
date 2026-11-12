# Roadmap

Scope of this engine over time. **Near-term is real; the theoretical section is
aspirational and unproven — do not treat it as shipping or as a commitment.**

## Now / near-term (TC1767 native CAN BSL)
- **BSL entry + loader upload + run on TC1767** — protocol decoded, loader written;
  final bench bring-up in progress.
- **EEPROM / DFLASH backup + restore — passwordless, universal** across TC1767 ECUs
  (no vendor tool, no dongle, no per-chip secret). This is the core deliverable.
- **PFLASH read/write** — supported by the loader, but **gated by that chip's per-chip
  password** (held in OTP). Obtaining the password per chip is out of this engine's scope today.
- **Per-ECU enablement** = documenting that board's boot-strap probe points (a catalog entry,
  not new code), because everything else is chip-level.

## Theoretical / planned (NOT built, NOT proven — flag as such everywhere)
These are considered likely-feasible future extensions and are worth factoring into product
ideas, but none is implemented or validated. Keep them clearly separated from the near-term.

- **Module-71 GPT-boot operations, including BSL password EXTRACTION.** A connector-level
  (no-case) GPT-gated path that today relies on vendor tooling. Bringing it in-house would add
  password extraction and a less-invasive access route. *Unproven; needs the GPT signal/timing
  and the extraction path reverse-engineered and validated on the bench.*
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
