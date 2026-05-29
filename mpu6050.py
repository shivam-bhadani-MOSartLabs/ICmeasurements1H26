# %%
from __future__ import annotations

from typing import TypedDict

from ad3 import AD3


# %% [markdown]
# ### Data container
# `SensorData` is a `TypedDict` so every consumer gets type-checked key access
# instead of relying on raw string keys.

# %%
class SensorData(TypedDict):
    accX:  list[int]
    accY:  list[int]
    accZ:  list[int]
    temp:  list[float]
    gyroX: list[int]
    gyroY: list[int]
    gyroZ: list[int]


def _empty_sensor_data() -> SensorData:
    return SensorData(accX=[], accY=[], accZ=[], temp=[], gyroX=[], gyroY=[], gyroZ=[])


# %% [markdown]
# ### Scale factors
# Raw 16-bit values need to be divided by a scale factor to get physical units.
#
# | Sensor | Default full-scale | Scale factor |
# |--------|--------------------|--------------|
# | Accel  | ±2 g               | 16384 LSB/g  |
# | Gyro   | ±250 °/s           | 131 LSB/°/s  |
# | Temp   | —                  | 340 LSB/°C, offset 36.53 °C |

# %%
_ACCEL_SCALE  : float = 16384.0   # LSB / g   (±2 g default)
_GYRO_SCALE   : float = 131.0     # LSB / °/s (±250 °/s default)
_TEMP_SCALE   : float = 340.0
_TEMP_OFFSET  : float = 36.53

# MPU-6050 register addresses
_REG_PWR_MGMT : int = 0x6B
_REG_ACC_BASE : int = 0x3B   # ACCEL_XOUT_H  (14 bytes: acc + temp + gyro)
_REG_GYRO_BASE: int = 0x43
_REG_TEMP_BASE: int = 0x41
_BURST_LEN    : int = 14
_MPU_ADDR     : int = 0x68


# %% [markdown]
# ### MPU6050 class
# Wraps the AD3 I2C interface and exposes clean methods for reading the IMU.
# All raw values are stored as integers; scaled (physical unit) values are
# computed on demand by the `scaled` property.

# %%
class MPU6050:
    """
    Driver for the InvenSense MPU-6050 IMU over I2C via an AD3 device.

    Parameters
    ----------
    supply  : float   Supply voltage for the AD3 power rail (V).
    clk_frq : int     I2C clock frequency in Hz (e.g. 400_000).
    scl_pin : int     Digital pin index for SCL.
    sda_pin : int     Digital pin index for SDA.
    """

    def __init__(
        self,
        supply : float,
        clk_frq: int,
        scl_pin: int,
        sda_pin: int,
    ) -> None:
        self._ad3 = AD3()
        self._ad3.supply(supply)
        self._ad3.init_i2c(clk_frq, scl_pin, sda_pin, _MPU_ADDR)

        # wake the MPU-6050 (clears SLEEP bit in PWR_MGMT_1)
        self._ad3.write_register(_REG_PWR_MGMT, 0x00)

        # latest raw readings
        self.acc_x: int   = 0
        self.acc_y: int   = 0
        self.acc_z: int   = 0
        self.temp : int   = 0
        self.gyro_x: int  = 0
        self.gyro_y: int  = 0
        self.gyro_z: int  = 0

        self._data: SensorData = _empty_sensor_data()

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> MPU6050:
        return self

    def __exit__(self, *_: object) -> None:
        self._ad3.close()

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _to_int16(high: int, low: int) -> int:
        """Combine two bytes into a signed 16-bit integer."""
        value = (high << 8) | low
        return value - 0x10000 if value & 0x8000 else value

    # ── core burst read ───────────────────────────────────────────────────────

    def read(self) -> bool:
        """
        Burst-read all 14 sensor bytes in one I2C transaction and update
        the internal raw values.

        Returns
        -------
        bool   True on success, False if the bus returned fewer than 14 bytes.
        """
        data: list[int] = self._ad3.read_data(_REG_ACC_BASE, _BURST_LEN)
        if len(data) != _BURST_LEN:
            return False

        self.acc_x  = self._to_int16(data[0],  data[1])
        self.acc_y  = self._to_int16(data[2],  data[3])
        self.acc_z  = self._to_int16(data[4],  data[5])
        self.temp   = self._to_int16(data[6],  data[7])
        self.gyro_x = self._to_int16(data[8],  data[9])
        self.gyro_y = self._to_int16(data[10], data[11])
        self.gyro_z = self._to_int16(data[12], data[13])
        return True

    # %% [markdown]
    # ### Scaled readings
    # `scaled` converts raw ADC counts to physical units:
    # accelerometer → **g**, gyroscope → **°/s**, temperature → **°C**.

    @property
    def scaled(self) -> dict[str, float]:
        """Return the latest readings converted to physical units."""
        return {
            "acc_x_g"  : self.acc_x  / _ACCEL_SCALE,
            "acc_y_g"  : self.acc_y  / _ACCEL_SCALE,
            "acc_z_g"  : self.acc_z  / _ACCEL_SCALE,
            "temp_c"   : self.temp   / _TEMP_SCALE + _TEMP_OFFSET,
            "gyro_x_ds": self.gyro_x / _GYRO_SCALE,
            "gyro_y_ds": self.gyro_y / _GYRO_SCALE,
            "gyro_z_ds": self.gyro_z / _GYRO_SCALE,
        }

    # ── individual reads (use read() for efficiency) ──────────────────────────

    def read_acc(self) -> tuple[int, int, int]:
        """Read only the accelerometer registers. Prefer read() for full data."""
        addr = _REG_ACC_BASE
        self.acc_x = self._to_int16(
            self._ad3.read_register(addr + 0) or 0,
            self._ad3.read_register(addr + 1) or 0,
        )
        self.acc_y = self._to_int16(
            self._ad3.read_register(addr + 2) or 0,
            self._ad3.read_register(addr + 3) or 0,
        )
        self.acc_z = self._to_int16(
            self._ad3.read_register(addr + 4) or 0,
            self._ad3.read_register(addr + 5) or 0,
        )
        return self.acc_x, self.acc_y, self.acc_z

    def read_gyro(self) -> tuple[int, int, int]:
        """Read only the gyroscope registers. Prefer read() for full data."""
        addr = _REG_GYRO_BASE
        self.gyro_x = self._to_int16(
            self._ad3.read_register(addr + 0) or 0,
            self._ad3.read_register(addr + 1) or 0,
        )
        self.gyro_y = self._to_int16(
            self._ad3.read_register(addr + 2) or 0,
            self._ad3.read_register(addr + 3) or 0,
        )
        self.gyro_z = self._to_int16(
            self._ad3.read_register(addr + 4) or 0,
            self._ad3.read_register(addr + 5) or 0,
        )
        return self.gyro_x, self.gyro_y, self.gyro_z

    def read_temp(self) -> float:
        """Read only the temperature register. Returns degrees Celsius."""
        addr = _REG_TEMP_BASE
        self.temp = self._to_int16(
            self._ad3.read_register(addr + 0) or 0,
            self._ad3.read_register(addr + 1) or 0,
        )
        return self.temp / _TEMP_SCALE + _TEMP_OFFSET

    # ── data logging ──────────────────────────────────────────────────────────

    def get_data(self) -> SensorData:
        """
        Call read() then append all raw values to the internal history buffer.

        Returns
        -------
        SensorData   The full accumulated history dict.
        """
        if not self.read():
            return self._data                   # skip append on I2C failure

        self._data["accX"].append(self.acc_x)
        self._data["accY"].append(self.acc_y)
        self._data["accZ"].append(self.acc_z)
        self._data["temp"].append(self.temp / _TEMP_SCALE + _TEMP_OFFSET)
        self._data["gyroX"].append(self.gyro_x)
        self._data["gyroY"].append(self.gyro_y)
        self._data["gyroZ"].append(self.gyro_z)
        return self._data

    def clear_data(self) -> None:
        """Reset the accumulated history buffer."""
        self._data = _empty_sensor_data()

    def __repr__(self) -> str:
        s = self.scaled
        return (
            f"MPU6050("
            f"acc=({s['acc_x_g']:.3f}, {s['acc_y_g']:.3f}, {s['acc_z_g']:.3f}) g  "
            f"gyro=({s['gyro_x_ds']:.2f}, {s['gyro_y_ds']:.2f}, {s['gyro_z_ds']:.2f}) °/s  "
            f"temp={s['temp_c']:.1f} °C)"
        )
