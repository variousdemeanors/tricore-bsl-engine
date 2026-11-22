"""
tricore-bsl-engine host CLI.

Drives the TC1767 native-BSL loader over CAN (SocketCAN) or ASC0 UART. Every
subcommand maps to a primitive the loader actually implements (loader/main.c):
connect/read/erase/program/write/verify/unlock/keepalive. No feature here exists
that the loader does not support.

Usually invoked through the top-level wrapper: `./tricore-bsl-engine <cmd> ...`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from . import protocol as p
from . import transport as tp
from . import session as se
from . import power as pw

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CAN_LOADER = os.path.join(ROOT, "loader", "canloader.bin")
DEFAULT_ASC_LOADER = os.path.join(ROOT, "loader", "ascloader.bin")


# ----------------------------------------------------------------- helpers

def parse_int(s: str) -> int:
    """Accept 0x.. / decimal, with optional K / M / KiB / MiB suffix."""
    s = s.strip()
    mult = 1
    for suf, m in (("MiB", 1 << 20), ("KiB", 1 << 10), ("M", 1 << 20),
                   ("K", 1 << 10), ("k", 1 << 10)):
        if s.endswith(suf):
            s = s[:-len(suf)]
            mult = m
            break
    return int(s, 0) * mult


def eprint(*a):
    print(*a, file=sys.stderr)


def _progress_bar(done, total, what):
    width = 28
    filled = int(width * done / total) if total else width
    sys.stderr.write(
        f"\r  {what}: [{'#' * filled}{'.' * (width - filled)}] {done}/{total}")
    if done >= total:
        sys.stderr.write("\n")
    sys.stderr.flush()


# -------------------------------------------------- interface / env checks

def check_interface(args) -> int:
    """Report whether the selected transport's interface is present & usable."""
    rc = 0
    if args.transport == "can":
        iface = args.interface
        path = f"/sys/class/net/{iface}"
        if not os.path.exists(path):
            eprint(f"[can] interface '{iface}' not found.")
            eprint(f"      Bring up a CAN adapter, e.g.:")
            eprint(f"        sudo ip link set {iface} up type can bitrate 500000")
            rc = 1
        else:
            state = "unknown"
            try:
                with open(os.path.join(path, "operstate")) as f:
                    state = f.read().strip()
            except OSError:
                pass
            if state in ("down", "notpresent"):
                eprint(f"[can] '{iface}' exists but is {state}. Bring it up:")
                eprint(f"        sudo ip link set {iface} up type can bitrate 500000")
                rc = 1
            else:
                print(f"[can] '{iface}' present (operstate={state}). OK.")
    else:
        port = args.port
        if not port:
            eprint("[asc] no serial port given (--port /dev/ttyUSB0)")
            return 1
        if not os.path.exists(port):
            eprint(f"[asc] serial port '{port}' not found. Plug in the adapter "
                   f"or check --port.")
            rc = 1
        else:
            readable = os.access(port, os.R_OK | os.W_OK)
            print(f"[asc] '{port}' present; "
                  f"{'read/write OK' if readable else 'NO r/w permission'}.")
            if not readable:
                eprint(f"      Add yourself to the 'dialout' group and re-login:")
                eprint(f"        sudo usermod -aG dialout $USER")
                rc = 1
        try:
            import serial  # noqa
        except ImportError:
            eprint("[asc] pyserial not installed (run --setup, or: pip install pyserial)")
            rc = 1
    return rc


# ------------------------------------------------------ transport / session

def make_transport(args):
    if args.transport == "can":
        return tp.CanTransport(interface=args.interface,
                               tx_id=args.tx_id, rx_id=args.rx_id,
                               frame_pace=args.frame_pace,
                               recover=getattr(args, "can_recover", False))
    return tp.AscTransport(port=args.port, upload_baud=args.upload_baud,
                           cmd_baud=args.cmd_baud)


def default_loader_path(args):
    if args.loader:
        return args.loader
    return DEFAULT_CAN_LOADER if args.transport == "can" else DEFAULT_ASC_LOADER


def open_session(args, need_enter):
    """Open the transport and return a live Session. If need_enter or --enter,
    run BootROM entry + loader upload; otherwise verify a resident loader."""
    transport = make_transport(args).open()
    sess = se.Session(transport)
    do_enter = need_enter or getattr(args, "enter", False)
    if do_enter:
        loader_bin = se.load_loader_bin(default_loader_path(args))
        gpio = getattr(args, "power_gpio", None)
        power = pw.make_power(gpio, active_high=not getattr(args, "power_active_low", False))

        def on_wait(nframes):
            if power.enabled:
                eprint(f"[*] Flooding INIT ({nframes} frames); GPIO{gpio} relay "
                       f"will power the ECU on ...")
            else:
                eprint(f"[*] Flooding INIT ({nframes} loader frames). "
                       f"POWER-CYCLE THE ECU NOW ...")
        sess.enter_bootloader(loader_bin, on_wait=on_wait, power=power,
                              power_off_ms=getattr(args, "power_off_ms", 600),
                              power_boot_ms=getattr(args, "power_boot_ms", 400))
        if not sess.keep_alive():
            raise se.EngineError("loader uploaded but not answering keep-alive "
                                 "(check loader startup: clock/WDT/CAN base).")
        eprint("[+] Loader is up (keep-alive OK).")
    else:
        sess.require_alive()
    return transport, sess


# ---------------------------------------------------------------- commands

def cmd_check(args):
    return check_interface(args)


def cmd_power(args):
    power = pw.make_power(args.gpio, active_high=not args.active_low)
    if args.state == "on":
        power.on()
        print(f"GPIO{args.gpio}: ECU ignition ON  ({power.status()})")
    elif args.state == "off":
        power.off()
        print(f"GPIO{args.gpio}: ECU ignition OFF ({power.status()})")
    else:
        print(f"GPIO{args.gpio}: {power.status()}")
    return 0


def cmd_connect(args):
    transport, sess = open_session(args, need_enter=True)
    try:
        print("Connected: TC1767 BSL loader is resident and responding.")
        print("You can now run read/write/verify/erase WITHOUT --enter while the "
              "ECU stays powered.")
        return 0
    finally:
        transport.close()


def cmd_keepalive(args):
    transport, sess = open_session(args, need_enter=False)
    try:
        ok = sess.keep_alive()
        print("loader alive" if ok else "no response")
        return 0 if ok else 1
    finally:
        transport.close()


def cmd_read(args):
    addr, length = parse_int(args.addr), parse_int(args.length)
    transport, sess = open_session(args, need_enter=False)
    try:
        eprint(f"[*] Reading {length:#x} B @ {addr:#010x} ...")
        data = sess.read(addr, length,
                         on_block=lambda d, t: _progress_bar(d, t, "read"))
        with open(args.out, "wb") as f:
            f.write(data)
        print(f"Read {len(data)} bytes -> {args.out}")
        return 0
    finally:
        transport.close()


def cmd_erase(args):
    addr = parse_int(args.addr)
    transport, sess = open_session(args, need_enter=False)
    try:
        eprint(f"[*] Erasing sector containing {addr:#010x} ...")
        sess.erase_sector(addr)
        print("Erase OK (sector acknowledged).")
        return 0
    finally:
        transport.close()


def cmd_unlock(args):
    transport, sess = open_session(args, need_enter=False)
    try:
        sess.unlock(parse_int(args.key0), parse_int(args.key1),
                    ucb=args.ucb, read_protection=args.read)
        print(f"{'READ' if args.read else 'WRITE'} protection temporarily "
              f"disabled (UCB {args.ucb}).")
        return 0
    finally:
        transport.close()


def _read_file(path):
    with open(path, "rb") as f:
        return f.read()


def cmd_program(args):
    addr = parse_int(args.addr)
    data = _read_file(args.infile)
    transport, sess = open_session(args, need_enter=False)
    try:
        eprint(f"[*] Programming {len(data):#x} B @ {addr:#010x} (no erase) ...")
        sess.write(addr, data, do_erase=False,
                   on_page=lambda d, t: _progress_bar(d, t, "program"))
        print("Program OK (loader read-back-verified each page).")
        return 0
    finally:
        transport.close()


def cmd_write(args):
    addr = parse_int(args.addr)
    data = _read_file(args.infile)
    sectors = None
    if args.erase_sectors:
        sectors = [parse_int(s) for s in args.erase_sectors.split(",") if s.strip()]
    transport, sess = open_session(args, need_enter=False)
    try:
        eprint(f"[*] Writing {len(data):#x} B @ {addr:#010x} "
               f"(erase={'no' if args.no_erase else 'yes'}) ...")
        sess.write(addr, data, do_erase=not args.no_erase, pflash_sectors=sectors,
                   on_page=lambda d, t: _progress_bar(d, t, "write"))
        print("Write OK (loader read-back-verified each page).")
        if args.verify:
            eprint("[*] Full read-back verify ...")
            r = sess.verify(addr, data,
                            on_block=lambda d, t: _progress_bar(d, t, "verify"))
            print("Verify OK." if r.ok
                  else f"VERIFY FAILED at offset {r.first_mismatch:#x}.")
            return 0 if r.ok else 1
        return 0
    finally:
        transport.close()


def cmd_verify(args):
    addr = parse_int(args.addr)
    data = _read_file(args.infile)
    transport, sess = open_session(args, need_enter=False)
    try:
        eprint(f"[*] Verifying {len(data):#x} B @ {addr:#010x} ...")
        r = sess.verify(addr, data,
                        on_block=lambda d, t: _progress_bar(d, t, "verify"))
        if r.ok:
            print(f"Verify OK: {r.length} bytes match.")
            return 0
        print(f"VERIFY FAILED: first mismatch at offset {r.first_mismatch:#x}.")
        return 1
    finally:
        transport.close()


# ---------------------------------------------------------------- parser

def add_transport_args(sp, enter_flag=False, power_flag=None):
    if power_flag is None:
        power_flag = enter_flag
    g = sp.add_argument_group("transport")
    g.add_argument("--transport", choices=("can", "asc"), default="can",
                   help="link to the ECU (default: can)")
    g.add_argument("--interface", default="can0",
                   help="SocketCAN interface for --transport can (default: can0)")
    g.add_argument("--port", default=None,
                   help="serial port for --transport asc, e.g. /dev/ttyUSB0")
    g.add_argument("--upload-baud", type=int, default=19200,
                   help="ASC upload baud (default: 19200)")
    g.add_argument("--cmd-baud", type=int, default=250000,
                   help="ASC command baud after switch (default: 250000)")
    g.add_argument("--tx-id", type=lambda s: int(s, 0), default=0x000,
                   help="CAN host->loader id (default: 0x000)")
    g.add_argument("--rx-id", type=lambda s: int(s, 0), default=0x008,
                   help="CAN loader->host id (default: 0x008)")
    g.add_argument("--frame-pace", type=float, default=0.001,
                   help="seconds between CAN frames, incl. the loader upload "
                        "(default: 0.001). Serial/slcan adapters echo a frame "
                        "when it hits the wire, not when it is ACKed, so the "
                        "upload can outrun the ROM's receive object -- raise to "
                        "~0.005 if entry ACKs but the upload stalls after a few "
                        "frames")
    g.add_argument("--can-recover", action="store_true",
                   help="software bus-off recovery during entry for CAN adapters "
                        "without restart-ms (gs_usb/candleLight); needs passwordless "
                        "sudo ip link")
    g.add_argument("--loader", default=None,
                   help="loader .bin to upload (default: loader/canloader.bin "
                        "or ascloader.bin)")
    if enter_flag:
        g.add_argument("--enter", action="store_true",
                       help="do BootROM BSL entry + loader upload before the op "
                            "(ECU must be reset on cue); omit to reuse a resident loader")
    if power_flag:
        pg = sp.add_argument_group("ecu power relay (optional, Raspberry Pi)")
        pg.add_argument("--power-gpio", type=int, default=None, metavar="N",
                        help="GPIO (BCM) driving the ECU ignition relay; the BSL "
                             "entry auto power-cycles it (e.g. --power-gpio 17)")
        pg.add_argument("--power-active-low", action="store_true",
                        help="relay is active-low (default: HIGH = ignition on)")
        pg.add_argument("--power-off-ms", type=int, default=600,
                        help="ms to hold the ECU off during reset (default: 600)")
        pg.add_argument("--power-boot-ms", type=int, default=400,
                        help="ms after power-on before flooding, for the BootROM to "
                             "reach its BSL listen window (default: 400)")


EXAMPLES = """\
examples:
  # one-time bring-up (power-cycle the ECU when prompted):
  ./tricore-bsl-engine connect --interface can0

  # back up both EEPROM/DFLASH banks (loader already resident):
  ./tricore-bsl-engine read  --addr 0xAFE00000 --length 0x8000 --out eeprom_bank0.bin
  ./tricore-bsl-engine read  --addr 0xAFE10000 --length 0x8000 --out eeprom_bank1.bin

  # restore a bank (auto-erases the 32K bank, programs, loader verifies each page):
  ./tricore-bsl-engine write  --addr 0xAFE00000 --in eeprom_bank0.bin --verify

  # verify a region against a file:
  ./tricore-bsl-engine verify --addr 0xAFE00000 --in eeprom_bank0.bin

  # do entry + read in a single command (freshly reset ECU):
  ./tricore-bsl-engine read --enter --addr 0xAFE00000 --length 0x8000 --out eeprom.bin

  # PFLASH (protected): unlock with the chip's own key, then write named sectors:
  ./tricore-bsl-engine unlock --key0 0xE1987A4C --key1 0xFB605D4C
  ./tricore-bsl-engine write  --addr 0xA0040000 --in sector4.bin \\
                              --erase-sectors 0xA0040000 --verify
"""


def build_parser():
    pr = argparse.ArgumentParser(
        prog="tricore-bsl-engine",
        description="TC1767 native-BSL flash engine (host CLI). Read/back up and "
                    "(emergency) restore TC1767 ECU flash over CAN or ASC.",
        epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = pr.add_subparsers(dest="cmd", required=True, metavar="<command>")

    s = sub.add_parser("check", help="check that the CAN/serial interface is present & permissioned")
    add_transport_args(s)
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("power", help="drive the ECU ignition relay GPIO on/off/status")
    s.add_argument("state", choices=("on", "off", "status"), help="relay action")
    s.add_argument("--gpio", type=int, default=17, help="BCM GPIO (default: 17)")
    s.add_argument("--active-low", action="store_true", help="relay is active-low")
    s.set_defaults(func=cmd_power)

    s = sub.add_parser("connect", aliases=["enter"],
                       help="enter the BootROM BSL and upload the loader (power-cycle the ECU on cue)")
    add_transport_args(s, power_flag=True)
    s.set_defaults(func=cmd_connect)

    s = sub.add_parser("keepalive", aliases=["ping"],
                       help="ping a resident loader (mode 0x3E)")
    add_transport_args(s, enter_flag=True)
    s.set_defaults(func=cmd_keepalive)

    s = sub.add_parser("read", help="read a region to a file (mode 0x07)")
    add_transport_args(s, enter_flag=True)
    s.add_argument("--addr", required=True, help="start address, e.g. 0xAFE00000")
    s.add_argument("--length", required=True, help="byte count, e.g. 0x8000 or 32K")
    s.add_argument("--out", required=True, help="output file")
    s.set_defaults(func=cmd_read)

    s = sub.add_parser("erase", help="erase the flash sector containing addr (mode 0x04)")
    add_transport_args(s, enter_flag=True)
    s.add_argument("--addr", required=True, help="any address inside the target sector")
    s.set_defaults(func=cmd_erase)

    s = sub.add_parser("program", help="program pages from a file WITHOUT erasing (mode 0x00)")
    add_transport_args(s, enter_flag=True)
    s.add_argument("--addr", required=True, help="start address (page-aligned)")
    s.add_argument("--in", dest="infile", required=True, help="input file")
    s.set_defaults(func=cmd_program)

    s = sub.add_parser("write", aliases=["flash"],
                       help="erase + program + (loader) verify a file to flash")
    add_transport_args(s, enter_flag=True)
    s.add_argument("--addr", required=True, help="start address")
    s.add_argument("--in", dest="infile", required=True, help="input file")
    s.add_argument("--no-erase", action="store_true",
                   help="skip erase (program into already-erased flash)")
    s.add_argument("--erase-sectors", default=None,
                   help="comma-separated PFLASH sector base addresses to erase "
                        "(required for PFLASH; DFLASH banks are automatic)")
    s.add_argument("--verify", action="store_true",
                   help="full read-back verify after writing")
    s.set_defaults(func=cmd_write)

    s = sub.add_parser("verify", help="read a region back and compare to a file")
    add_transport_args(s, enter_flag=True)
    s.add_argument("--addr", required=True, help="start address")
    s.add_argument("--in", dest="infile", required=True, help="reference file")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("unlock",
                       help="temporarily disable PFLASH write/read protection with the chip's own key words")
    add_transport_args(s, enter_flag=True)
    s.add_argument("--key0", required=True, help="unlock word 0 (operator-supplied)")
    s.add_argument("--key1", required=True, help="unlock word 1 (operator-supplied)")
    s.add_argument("--ucb", type=int, default=0, help="UCB user index (default: 0)")
    s.add_argument("--read", action="store_true",
                   help="disable READ protection instead of WRITE")
    s.set_defaults(func=cmd_unlock)

    return pr


def main(argv=None):
    pr = build_parser()
    args = pr.parse_args(argv)
    try:
        return args.func(args)
    except (tp.TransportError, se.EngineError) as e:
        eprint(f"error: {e}")
        return 2
    except KeyboardInterrupt:
        eprint("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
