# Makefile -- GammaFlash TC1767 read-only CANLoader (HighTec Free TriCore GCC).
#
# Produces canloader.elf -> canloader.bin / canloader.hex, loaded by the TC1767
# BootROM CAN BSL into SPRAM 0xD4000000. The `check-size` target FAILS if the
# binary exceeds the 0x1400 (5120 B) SPRAM loader window; the linker ASSERT in
# loader.ld is the same gate at link time.
#
# TODO(bench): set TRICORE_PREFIX to your HighTec toolchain's tool prefix (e.g.
# tricore-gcc, or <install>/bin/tricore-gcc). Confirm the -mcpu value for TC1767.

TRICORE_PREFIX ?= tricore-
CC      := $(TRICORE_PREFIX)gcc
OBJCOPY := $(TRICORE_PREFIX)objcopy
SIZE    := $(TRICORE_PREFIX)size

# TODO(bench): confirm the right -mcpu / -mtc* flag for TC1767 in your toolchain.
MCPU    ?= -mcpu=tc1767

CFLAGS  := $(MCPU) -Os -ffreestanding -fno-common -fomit-frame-pointer \
           -Wall -Wextra -ffunction-sections -fdata-sections
LDFLAGS := $(MCPU) -nostartfiles -nostdlib -Wl,--gc-sections -T loader.ld

MAX_BIN := 5120   # 0x1400

OBJS := crt0.o main.o flash.o

.PHONY: all clean check-size
all: canloader.bin canloader.hex check-size

crt0.o: crt0.S tc1767_regs.h
	$(CC) $(CFLAGS) -c -o $@ $<

main.o: main.c tc1767_regs.h flash.h
	$(CC) $(CFLAGS) -c -o $@ $<

flash.o: flash.c flash.h tc1767_regs.h
	$(CC) $(CFLAGS) -c -o $@ $<

canloader.elf: $(OBJS) loader.ld
	$(CC) $(LDFLAGS) -o $@ $(OBJS)
	$(SIZE) $@

canloader.bin: canloader.elf
	$(OBJCOPY) -O binary $< $@

canloader.hex: canloader.elf
	$(OBJCOPY) -O ihex $< $@

check-size: canloader.bin
	@sz=$$(wc -c < canloader.bin); \
	echo "canloader.bin = $$sz B (limit $(MAX_BIN))"; \
	if [ $$sz -gt $(MAX_BIN) ]; then \
	  echo "ERROR: loader image exceeds the $(MAX_BIN) B SPRAM window"; exit 1; \
	fi

clean:
	rm -f $(OBJS) canloader.elf canloader.bin canloader.hex
