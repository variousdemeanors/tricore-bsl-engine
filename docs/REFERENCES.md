# References

The authoritative sources behind this engine. They are **referenced, not redistributed** —
obtain them from the publisher under their terms. The technical facts (addresses, protocol,
sequences) are documented in our own words in `IMPLEMENTATION_GUIDE.md`.

## Infineon (primary)
- **AP32132 — "TriCore AUDO-F Flash Download Using Bootstrap Loader"** (application note + example
  source package). THE authoritative spec for the TC1767 native CAN/ASC BSL: init frame format,
  the id transform, the SPRAM load address `0xD4000000`, and the example `CANLoader` (its `crt0`
  does the clock-reset + WDT; its `main.c` CAN layer uses MultiCAN base `0xF0005000`). Download
  from infineon.com (gated; free account). This is the single most useful document.
- **AP32136 — "TriCore AUDO-NG Flash Download Using Bootstrap Loader"** — the AUDO-NG sibling
  (TC1796/TC1766). Useful for contrast; note AUDO-NG uses MultiCAN base `0xF0004600`, **not** the
  AUDO-F `0xF0005000` — a common porting trap.
- **TC1767 User Manual** — MultiCAN chapter (node/message-object registers, bit timing), SCU/clock
  chapter (PLL/prescaler, the `0xF00005xx` clock + WDT registers), DMU/flash chapter (Command
  Sequence Interface, UCB protection, sector map).
- **TC1767 Data Sheet** — memory map, pinout, electricals.

## Open-source reference implementations (CAN BSL, other TriCore parts)
- **bri3d/TC1791_CAN_BSL** — VW-side TC1791 (AUDO-MAX) CAN BSL host+loader. Same family of
  approach; TC1791 also uses MultiCAN base `0xF0005000`.
- **fastboatster/TC1796_CAN_BSL** — TC1796 (AUDO-NG) CAN BSL; pure-inherit MO0/MO1 model. Note its
  `0xF0004600` base is AUDO-NG and does **not** apply to TC1767.

## Toolchain
- **TriCore GNU GCC** (e.g. the `tricore-gcc-toolchain` 13.x releases) — builds the loader. It
  ships `crt0-tc1x.S` (authoritative WDT/ENDINIT sequence) and per-derivative memory scripts.
  See `loader/TOOLCHAIN.md`.

## Porting trap, highlighted
The single costliest mistake when porting from AUDO-NG references: the **MultiCAN message-object
base is `0xF0005000` on TC1767 (AUDO-F)**, not `0xF0004600` (AUDO-NG). Using the wrong base makes
the loader run but stay completely silent on CAN.
