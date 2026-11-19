# Makefile -- GammaFlash TC1767 CANLoader (HighTec Free TriCore GCC).
#
# Two build targets, same command-block logic (main.c), different transport:
#   make            -> canloader.{bin,hex}: MultiCAN, loaded by the TC1767 BootROM
#                      CAN BSL into SPRAM.
#   make asc        -> ascloader.{bin,hex}: TC1767 ASC0 UART (loader/asc/asc_io.c),
#                      loaded by the BootROM's ASC/serial BSL instead.
# `check-size` FAILS either build if the binary exceeds the 0x1400 (5120 B)
# SPRAM loader window; the linker ASSERT in loader.ld is the same gate at link
# time.
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

OBJS     := crt0.o main.o flash.o
ASC_OBJS := crt0.o asc_main.o flash.o asc/asc_io.o

.PHONY: all asc clean check-size check-size-asc
all: canloader.bin canloader.hex check-size

asc: ascloader.bin ascloader.hex check-size-asc

crt0.o: crt0.S tc1767_regs.h
	$(CC) $(CFLAGS) -c -o $@ $<

main.o: main.c tc1767_regs.h flash.h
	$(CC) $(CFLAGS) -c -o $@ $<

# Same source as main.o, built with -DASC_TRANSPORT (see main.c's transport switch).
asc_main.o: main.c tc1767_regs.h flash.h asc/asc_io.h
	$(CC) $(CFLAGS) -DASC_TRANSPORT -c -o $@ main.c

asc/asc_io.o: asc/asc_io.c asc/asc_io.h
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

ascloader.elf: $(ASC_OBJS) loader.ld
	$(CC) $(LDFLAGS) -o $@ $(ASC_OBJS)
	$(SIZE) $@

ascloader.bin: ascloader.elf
	$(OBJCOPY) -O binary $< $@

ascloader.hex: ascloader.elf
	$(OBJCOPY) -O ihex $< $@

check-size: canloader.bin
	@sz=$$(wc -c < canloader.bin); \
	echo "canloader.bin = $$sz B (limit $(MAX_BIN))"; \
	if [ $$sz -gt $(MAX_BIN) ]; then \
	  echo "ERROR: loader image exceeds the $(MAX_BIN) B SPRAM window"; exit 1; \
	fi

check-size-asc: ascloader.bin
	@sz=$$(wc -c < ascloader.bin); \
	echo "ascloader.bin = $$sz B (limit $(MAX_BIN))"; \
	if [ $$sz -gt $(MAX_BIN) ]; then \
	  echo "ERROR: loader image exceeds the $(MAX_BIN) B SPRAM window"; exit 1; \
	fi

clean:
	rm -f $(OBJS) $(ASC_OBJS) canloader.elf canloader.bin canloader.hex \
	      ascloader.elf ascloader.bin ascloader.hex
