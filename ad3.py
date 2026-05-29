# %%
from __future__ import annotations

import sys
import time
from ctypes import CDLL, byref, c_double, c_int, c_ubyte, cdll
from os import sep
from pathlib import Path
from typing import Optional


def _load_dwf() -> tuple[CDLL, str]:
    """Load the DWF shared library and return (dwf, constants_path)."""
    platform = sys.platform
    if platform.startswith("win"):
        return (
            cdll.dwf,
            str(Path("C:/Program Files (x86)/Digilent/WaveFormsSDK/samples/py")),
        )
    if platform.startswith("darwin"):
        return (
            cdll.LoadLibrary("/Library/Frameworks/dwf.framework/dwf"),
            "/Applications/WaveForms.app/Contents/Resources/SDK/samples/py",
        )
    return (
        cdll.LoadLibrary("libdwf.so"),
        "/usr/share/digilent/waveforms/samples/py",
    )


class AD3:
    """
    Wrapper for the Digilent WaveForms SDK (AD3 / Analog Discovery 3).

    Typical usage
    -------------
    dev = AD3()
    dev.supply(3.3)
    dev.init_i2c(clk_frq=400_000, scl_pin=0, sda_pin=1, dev_addr=0x68)
    data = dev.read_data(reg=0x3B, length=6)
    dev.close()
    """

    # ── construction / teardown ───────────────────────────────────────────────

    def __init__(self) -> None:
        self._dwf, constants_path = _load_dwf()

        sys.path.append(constants_path)
        import dwfconstants as _c  # type: ignore[import]

        self._dwf.FDwfDeviceCloseAll()

        filter_flags = c_int(_c.enumfilterType.value | _c.enumfilterUSB.value)
        device_count = c_int()
        self._dwf.FDwfEnum(filter_flags, byref(device_count))

        self._hdwf = c_int()
        self._dwf.FDwfDeviceOpen(c_int(-1), byref(self._hdwf))
        if self._hdwf.value == 0:
            raise RuntimeError("Failed to open AD3 device.")

        self._device_addr: int = 0          # set by init_i2c
        print(f"AD3 opened — handle {self._hdwf.value}")

    def close(self) -> None:
        """Release the device handle."""
        self._dwf.FDwfDeviceCloseAll()

    # context-manager support: `with AD3() as dev:`
    def __enter__(self) -> AD3:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── power supply ──────────────────────────────────────────────────────────

    def supply(self, voltage: float) -> float:
        """
        Enable the positive supply rail and return the measured voltage (V).

        Parameters
        ----------
        voltage : float
            Target output voltage in Volts.

        Returns
        -------
        float
            Measured supply voltage after settling.
        """
        self._dwf.FDwfAnalogIOReset(self._hdwf)
        self._dwf.FDwfAnalogIOChannelNodeSet(self._hdwf, c_int(0), c_int(1), c_double(voltage))
        self._dwf.FDwfAnalogIOChannelNodeSet(self._hdwf, c_int(0), c_int(0), c_double(1))
        self._dwf.FDwfAnalogIOEnableSet(self._hdwf, c_int(1))
        time.sleep(0.5)

        vpos = c_double()
        self._dwf.FDwfAnalogIOStatus(self._hdwf)
        self._dwf.FDwfAnalogIOChannelNodeStatus(self._hdwf, c_int(0), c_int(1), byref(vpos))
        print(f"Supply: +{vpos.value:.3f} V")
        return vpos.value

    # ── I2C setup ─────────────────────────────────────────────────────────────

    def init_i2c(
        self,
        clk_frq: int,
        scl_pin: int,
        sda_pin: int,
        dev_addr: int,
    ) -> None:
        """
        Configure the digital I2C interface.

        Parameters
        ----------
        clk_frq  : int   Clock frequency in Hz (e.g. 400_000).
        scl_pin  : int   Digital pin index for SCL.
        sda_pin  : int   Digital pin index for SDA.
        dev_addr : int   7-bit I2C device address (shifted internally).
        """
        self._device_addr = dev_addr << 1
        self._dwf.FDwfDigitalI2cRateSet(self._hdwf, c_double(clk_frq))
        self._dwf.FDwfDigitalI2cSclSet(self._hdwf, c_int(scl_pin))
        self._dwf.FDwfDigitalI2cSdaSet(self._hdwf, c_int(sda_pin))
        inak = c_int()
        self._dwf.FDwfDigitalI2cClear(self._hdwf, byref(inak))

    # ── I2C register access ───────────────────────────────────────────────────

    def write_register(self, reg: int, value: int) -> bool:
        """
        Write a single byte to a register.

        Parameters
        ----------
        reg   : int   Register address (0–255).
        value : int   Byte value to write (0–255).

        Returns
        -------
        bool   True on ACK, False on NAK.
        """
        inak = c_int()
        tx = (c_ubyte * 2)(reg, value)
        self._dwf.FDwfDigitalI2cWrite(
            self._hdwf, c_int(self._device_addr), tx, c_int(2), byref(inak)
        )
        return inak.value == 0

    def read_register(self, reg: int) -> Optional[int]:
        """
        Read a single byte from a register.

        Parameters
        ----------
        reg : int   Register address (0–255).

        Returns
        -------
        int | None   Byte value on success, None on NAK.
        """
        inak = c_int()
        tx = (c_ubyte * 1)(reg)
        self._dwf.FDwfDigitalI2cWrite(
            self._hdwf, c_int(self._device_addr), tx, c_int(1), byref(inak)
        )
        if inak.value != 0:
            return None

        rx = (c_ubyte * 1)()
        self._dwf.FDwfDigitalI2cRead(
            self._hdwf, c_int(self._device_addr), rx, c_int(1), byref(inak)
        )
        return rx[0] if inak.value == 0 else None

    def read_data(self, reg: int, length: int) -> list[int]:
        """
        Burst-read `length` bytes starting at `reg` using a repeated-start.

        Parameters
        ----------
        reg    : int   Starting register address.
        length : int   Number of bytes to read.

        Returns
        -------
        list[int]   Byte values on success, empty list on NAK.
        """
        if length <= 0:
            return []

        inak = c_int()
        tx = (c_ubyte * 1)(reg)
        rx = (c_ubyte * length)()
        self._dwf.FDwfDigitalI2cWriteRead(
            self._hdwf,
            c_int(self._device_addr),
            tx, c_int(1),
            rx, c_int(length),
            byref(inak),
        )
        return list(rx) if inak.value == 0 else []