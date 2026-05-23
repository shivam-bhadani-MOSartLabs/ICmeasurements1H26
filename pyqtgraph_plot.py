from __future__ import annotations

import sys
import numpy as np
import pyqtgraph as pg

from PySide6.QtWidgets import QApplication
from PySide6.QtCore    import QTimer, Qt
from PySide6.QtGui     import QKeyEvent, QFont

TIMER_MS    : int   = 25
HISTORY_LEN : int   = 300

from mpu6050 import MPU6050

# [1,2,3]*0.5=[0.5,1,1.5]

class flt:
    def __init__(self):
        self.ax=np.array([0,0,0])
        self.gyro=np.array([0,0,0])

    def filter_ax(self, arr):
       arr_flt = 0.5*self.ax + 0.5*arr
       self.ax=arr_flt
       return arr_flt

    def filter_gyro(self,arr):
        arr_flt = 0.5*self.gyro + 0.5*arr
        self.gyro = arr_flt
        return arr_flt

prev_flt = flt()



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
                accel_raw[i] / 16384.0
            )

            self._bufs[f"{axis}_flt"].append(
                accel_flt[i] / 131.0
            )

        # gyroscope
        for i, axis in enumerate(["gx", "gy", "gz"]):

            self._bufs[f"{axis}_raw"].append(
                gyro_raw[i] 
            )

            self._bufs[f"{axis}_flt"].append(
                gyro_flt[i]
            )

        # redraw
        for key, curve in self._curves.items():
            curve.setData(self._xs, self._bufs[key].data)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:

    app = QApplication.instance() or QApplication(sys.argv)
    imu = MPU6050(5, 400_000, 0, 1)
    imu._ad3.write_register(0x1a,0x03)
    imu._ad3.write_register(0x19,0x09)

    stepp = 1
    DT = 1e-1
    # plot window
    win = LPFPlotWindow()
    win.show()

    # ── update loop ─────────────────────────────────────────────────────────

    def update() -> None:

        nonlocal stepp

      
        # signal_amp = 1.0
        # noise_std  = 1e-1
        # ampp = [0,1,2]
        # accel_clean = signal_amp * np.sin(stepp * DT) + np.array(ampp)
        # gyro_clean  = signal_amp * np.cos(stepp * DT) + np.array(ampp)

        # accel_flt = accel_clean * np.ones(3)
        # gyro_flt  = gyro_clean  * np.ones(3)

        # accel_raw = accel_flt + noise_std * np.random.randn(3)
        # gyro_raw  = gyro_flt  + noise_std * np.random.randn(3)
        # stepp+=1

        accel_raw=imu.read_acc()
        accel_raw=np.array(accel_raw)
        gyro_raw=imu.read_gyro()
        gyro_raw=np.array(gyro_raw)
        accel_flt = prev_flt.filter_ax(accel_raw)
        gyro_flt=prev_flt.filter_gyro(gyro_raw)
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