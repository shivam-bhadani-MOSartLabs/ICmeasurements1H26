from __future__ import annotations

import sys
import numpy as np
import pyqtgraph as pg

from PySide6.QtWidgets import QApplication
from PySide6.QtCore    import QTimer, Qt
from PySide6.QtGui     import QKeyEvent, QFont

from mpu6050    import MPU6050

class LowPassFilter:
    """
    First-order IIR low-pass filter.
    y[n] = alpha * x[n] + (1 - alpha) * y[n-1]

    Parameters
    ----------
    alpha  : float   Smoothing factor [0, 1]. Lower = more smoothing.
    n_axes : int     Number of independent channels (default 3 for x/y/z).
    """

    def __init__(self, alpha: float = 0.2, n_axes: int = 3) -> None:
        self.alpha  = alpha
        self._state = np.zeros(n_axes)
        self._init  = False

    def update(self, sample: list[int] | np.ndarray) -> np.ndarray:
        x = np.array(sample, dtype=np.float64)
        if not self._init:
            self._state = x.copy()
            self._init  = True
        self._state = self.alpha * x + (1.0 - self.alpha) * self._state
        return self._state.copy()

    def reset(self) -> None:
        self._state = np.zeros_like(self._state)
        self._init  = False

# ── MPU-6050 default scale factors ────────────────────────────────────────────
GYRO_SCALE  : float = 131.0    # LSB / (°/s)  at ±250 °/s
ACCEL_SCALE : float = 16384.0  # LSB / g       at ±2 g

# ── config ────────────────────────────────────────────────────────────────────
SUPPLY_V    : float = 5.0
CLK_FRQ     : int   = 400_000
SCL_PIN     : int   = 0
SDA_PIN     : int   = 1

TIMER_MS    : int   = 25
HISTORY_LEN : int   = 300

pg.setConfigOptions(antialias=True, useOpenGL=False)

# ── rolling buffer ────────────────────────────────────────────────────────────

class RingBuffer:
    def __init__(self, length: int) -> None:
        self._buf = np.zeros(length)
        self._len = length

    def append(self, val: float) -> None:
        self._buf = np.roll(self._buf, -1)
        self._buf[-1] = val

    @property
    def data(self) -> np.ndarray:
        return self._buf


# ── colors ────────────────────────────────────────────────────────────────────

COLORS = {
    # accel
    "ax_raw": (255, 80,  80,  180),
    "ax_flt": (255, 80,  80,  255),

    "ay_raw": (80,  200, 80,  180),
    "ay_flt": (80,  200, 80,  255),

    "az_raw": (80,  130, 255, 180),
    "az_flt": (80,  130, 255, 255),

    # gyro
    "gx_raw": (255, 160, 0,   180),
    "gx_flt": (255, 160, 0,   255),

    "gy_raw": (200, 80,  200, 180),
    "gy_flt": (200, 80,  200, 255),

    "gz_raw": (0,   200, 200, 180),
    "gz_flt": (0,   200, 200, 255),
}


def _pen(key: str, width: int = 1, style=Qt.PenStyle.SolidLine):
    return pg.mkPen(color=COLORS[key], width=width, style=style)


def _dashed(key: str):
    return _pen(key, width=1, style=Qt.PenStyle.DashLine)


# ── plot window ───────────────────────────────────────────────────────────────

class LPFPlotWindow(pg.GraphicsLayoutWidget):

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Low Pass Filter Signals")
        self.resize(1000, 700)

        self.setBackground("#0d0d1a")

        N = HISTORY_LEN
        self._xs = np.arange(N)

        # buffers
        self._bufs: dict[str, RingBuffer] = {
            k: RingBuffer(N) for k in [
                "ax_raw","ay_raw","az_raw",
                "ax_flt","ay_flt","az_flt",

                "gx_raw","gy_raw","gz_raw",
                "gx_flt","gy_flt","gz_flt",
            ]
        }

        font = QFont("Courier", 8)

        def _subplot(title: str, ylabel: str, row: int):
            p = self.addPlot(row=row, col=0)

            p.setTitle(title, color="#aaa", size="10pt")
            p.setLabel("left", ylabel, color="#888")

            p.showGrid(x=True, y=True, alpha=0.2)

            p.getAxis("bottom").setStyle(tickFont=font)
            p.getAxis("left").setStyle(tickFont=font)

            p.addLegend(offset=(5, 5), labelTextSize="8pt")

            return p

        self._curves = {}

        # ── accelerometer ────────────────────────────────────────────────────

        p1 = _subplot("Accelerometer LPF", "g", 0)

        for axis, label in [("ax", "X"), ("ay", "Y"), ("az", "Z")]:

            self._curves[f"{axis}_raw"] = p1.plot(
                pen=_dashed(f"{axis}_raw"),
                name=f"{label} raw"
            )

            self._curves[f"{axis}_flt"] = p1.plot(
                pen=_pen(f"{axis}_flt", 2),
                name=f"{label} filtered"
            )

        # ── gyroscope ────────────────────────────────────────────────────────

        p2 = _subplot("Gyroscope LPF", "°/s", 1)

        for axis, label in [("gx", "X"), ("gy", "Y"), ("gz", "Z")]:

            self._curves[f"{axis}_raw"] = p2.plot(
                pen=_dashed(f"{axis}_raw"),
                name=f"{label} raw"
            )

            self._curves[f"{axis}_flt"] = p2.plot(
                pen=_pen(f"{axis}_flt", 2),
                name=f"{label} filtered"
            )

    # ── update ───────────────────────────────────────────────────────────────

    def push(
        self,
        accel_raw: np.ndarray,
        accel_flt: np.ndarray,
        gyro_raw : np.ndarray,
        gyro_flt : np.ndarray,
    ) -> None:

        # accelerometer
        for i, axis in enumerate(["ax", "ay", "az"]):

            self._bufs[f"{axis}_raw"].append(
                accel_raw[i] / ACCEL_SCALE
            )

            self._bufs[f"{axis}_flt"].append(
                accel_flt[i] / ACCEL_SCALE
            )

        # gyroscope
        for i, axis in enumerate(["gx", "gy", "gz"]):

            self._bufs[f"{axis}_raw"].append(
                gyro_raw[i] / GYRO_SCALE
            )

            self._bufs[f"{axis}_flt"].append(
                gyro_flt[i] / GYRO_SCALE
            )

        # redraw
        for key, curve in self._curves.items():
            curve.setData(self._xs, self._bufs[key].data)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:

    app = QApplication.instance() or QApplication(sys.argv)

    imu = MPU6050(
        SUPPLY_V,
        CLK_FRQ,
        SCL_PIN,
        SDA_PIN
    )

    # low-pass filters
    lpf_accel = LowPassFilter(alpha=0.2)
    lpf_gyro  = LowPassFilter(alpha=0.2)

    # plot window
    win = LPFPlotWindow()
    win.show()

    # ── update loop ─────────────────────────────────────────────────────────

    def update() -> None:

        try:
            gyro_raw  = np.array(
                imu.read_gyro(),
                dtype=np.float64
            )

            accel_raw = np.array(
                imu.read_acc(),
                dtype=np.float64
            )

        except Exception as e:
            print(f"Read error: {e}")
            return

        accel_flt = lpf_accel.update(accel_raw)
        gyro_flt  = lpf_gyro.update(gyro_raw)

        win.push(
            accel_raw,
            accel_flt,
            gyro_raw,
            gyro_flt,
        )

    timer = QTimer()

    timer.timeout.connect(update)

    timer.start(TIMER_MS)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()