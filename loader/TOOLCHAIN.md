# TriCore toolchain (resolved 2026-11-06)

Prebuilt, working TriCore GCC toolchain found: https://nomore201.github.io/tricore-gcc-toolchain/
(releases: https://github.com/NoMore201/tricore-gcc-toolchain/releases, v13.4.1 used here).

Build command that works (binary prefix is `tricore-elf-`, not `tricore-`; CPU flag is
`-mcpu=tc1767`, a name this toolchain recognizes exactly):

```
make TRICORE_PREFIX=tricore-elf- MCPU=-mcpu=tc1767          # canloader.bin (MultiCAN)
make asc TRICORE_PREFIX=tricore-elf- MCPU=-mcpu=tc1767       # ascloader.bin (ASC0 UART)
```

Builds clean and reproduces byte-exact, ELF entry point = SPRAM load address, architecture =
TriCore V1.3.1 (matches TC1767). One linker warning (LOAD segment has RWX permissions) — benign
for a flat SPRAM loader image, not yet silenced.

**Both transports and the full command set (read, erase, program, temporary protection-disable)
are proven on real TC1767 silicon** — boot-mode entry, loader upload, ROM-jump, and the write
path all confirmed on the bench (see README "Status / provenance"). If you're porting to new
hardware, re-verify on your own part before trusting it.
