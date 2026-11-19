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

## Other toolchain options (community-sourced, not verified by this project)
The one above is what this repo is built and tested with. If it doesn't work for you, or you want
something newer / GDB / a simulator, these have come up in the TriCore RE community — do your own
diligence (these are third-party, unaffiliated with this repo, and unverified by us):

- **GCC 4.9.4, full GPL source + prebuilt binaries** (Linux, Windows/MinGW), rebuilt from
  HighTec's GPL source dump: `github.com/volumit/package_494` (source + build scripts),
  `github.com/volumit/tricore_gcc494_linux_bins`, `github.com/volumit/tricore_gcc494_mingw_bins`.
- **GDB for TriCore**: `github.com/volumit/gdb-tricore`.
- **TriCore QEMU fork**: `github.com/volumit/qemu` — potentially useful for testing the loader's
  portable logic (everything outside `tc1767_regs.h` / the transport layer) without real silicon;
  we haven't tried this ourselves.
- **Newer toolchain with modern C++ support**: `github.com/EEESlab/tricore-gcc-toolchain-11.3.0`,
  with a matching VS Code setup at `github.com/jbx81-1337/vscode-tricore-skeleton`.
- Cheap real hardware to bench against (different TriCore family, AURIX not AUDO, but same
  toolchain ecosystem): Infineon's `KIT_A2G_TC334_LITE` / `KIT_A2G_TC275_LITE` starter boards.
