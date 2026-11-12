# TriCore toolchain (resolved 2026-11-06)

Prebuilt, working TriCore GCC toolchain found: https://nomore201.github.io/tricore-gcc-toolchain/
(releases: https://github.com/NoMore201/tricore-gcc-toolchain/releases, v13.4.1 used here).

Build command that works (binary prefix is `tricore-elf-`, not `tricore-`; CPU flag is
`-mcpu=tc1767`, a name this toolchain recognizes exactly):

```
make TRICORE_PREFIX=tricore-elf- MCPU=-mcpu=tc1767
```

Confirmed 2026-11-06: builds clean, `canloader.bin` = 1168 B (limit 5120 B), ELF entry point
= `0xD4000000` (matches SPRAM load address), architecture = TriCore V1.3.1 (matches TC1767).
One linker warning (LOAD segment has RWX permissions) — benign for a flat SPRAM loader image,
not yet silenced.

Not yet done: bench flashing/loading via the real GPT-toggle boot-mode entry sequence, and
confirming the CAN BSL read protocol against real hardware (host-side conformance tests already
exist and pass in `test_bsl_*.py`; this only confirms the firmware image now compiles and links
correctly for the target).
