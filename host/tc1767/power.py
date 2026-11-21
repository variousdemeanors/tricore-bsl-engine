"""
Optional ECU ignition-power control via a host GPIO driving a relay.

Used to automate the BSL power-cycle: the TC1767 BootROM only listens for the
CAN-BSL init flood in a short window right after reset, so the host powers the
ECU OFF, starts flooding, then powers it ON and catches the ACK.

Backend: `pinctrl` (Raspberry Pi 5 and current Pi OS). pinctrl sets the pad
register and the level PERSISTS after the process exits -- important here,
because the relay must stay energized between separate CLI invocations
(`connect` powers on and exits; later `read`/`write` talk to the still-powered
resident loader). A held libgpiod/gpiozero line would drop on process exit and
cut power, so it is deliberately not used for this.

Default: GPIO17, active-high (drive HIGH = ignition ON), per the bench relay.
"""

from __future__ import annotations

import shutil
import subprocess
import time


class PowerError(RuntimeError):
    pass


class NullPower:
    """No GPIO configured: the operator power-cycles the ECU by hand."""
    enabled = False

    def on(self):
        pass

    def off(self):
        pass

    def status(self):
        return "manual (no --power-gpio)"


class PinctrlPower:
    def __init__(self, gpio=17, active_high=True):
        self.gpio = int(gpio)
        self.active_high = active_high
        self.enabled = True
        if not shutil.which("pinctrl"):
            raise PowerError(
                "pinctrl not found -- it drives the ECU power relay. On Raspberry "
                "Pi OS: sudo apt install raspi-utils (provides pinctrl). Or omit "
                "--power-gpio and power-cycle the ECU manually.")

    def _set(self, level_high: bool):
        # pinctrl set <n> op dh|dl  -> output, drive high/low
        drive = "dh" if level_high else "dl"
        try:
            subprocess.run(["pinctrl", "set", str(self.gpio), "op", drive],
                           check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise PowerError(f"pinctrl set {self.gpio} op {drive} failed: "
                             f"{e.stderr.strip() or e}") from e

    def on(self):
        """Energize ECU ignition."""
        self._set(self.active_high)

    def off(self):
        """De-energize ECU ignition."""
        self._set(not self.active_high)

    def status(self):
        try:
            out = subprocess.run(["pinctrl", "get", str(self.gpio)],
                                 check=True, capture_output=True, text=True)
            return out.stdout.strip()
        except Exception as e:  # noqa: BLE001
            return f"unknown ({e})"


def make_power(gpio=None, active_high=True):
    if gpio is None:
        return NullPower()
    return PinctrlPower(gpio=gpio, active_high=active_high)
