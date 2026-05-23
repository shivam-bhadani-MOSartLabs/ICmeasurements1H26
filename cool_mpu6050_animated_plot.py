# %% [markdown]
# ### creating the AD3 class
# %%
from ctypes import cdll, c_int, byref, c_ubyte, c_double
import time
from sys import path
import sys
from os import sep
import numpy as np

class ad3:
    
    def __init__(self):
        if sys.platform.startswith("win"):
            self.dwf = cdll.dwf
            constants_path = "C:" + sep + "Program Files (x86)" + sep + "Digilent" + sep + "WaveFormsSDK" + sep + "samples" + sep + "py"
        elif sys.platform.startswith("darwin"):
            self.dwf = cdll.LoadLibrary("/Library/Frameworks/dwf.framework/dwf")
            constants_path = "/Applications/WaveForms.app/Contents/Resources/SDK/samples/py"
        else:
            self.dwf = cdll.LoadLibrary("libdwf.so")
            constants_path = "/usr/share/digilent/waveforms/samples/py"
        
        path.append(constants_path)
        import dwfconstants as constants
        
        self.dwf.FDwfDeviceCloseAll()
        filter_flags = c_int(constants.enumfilterType.value | constants.enumfilterUSB.value)
        device_count = c_int()
        self.dwf.FDwfEnum(filter_flags, byref(device_count))
        
        self.hdwf = c_int()
        self.dwf.FDwfDeviceOpen(c_int(-1), byref(self.hdwf))
        if self.hdwf.value == 0:
            raise RuntimeError("Failed to open device.")
        print(self.hdwf.value)
        
    
    def write_register(self,reg, value):
        iNak = c_int()
        rgTX = (c_ubyte * 2)(reg, value)
        self.dwf.FDwfDigitalI2cWrite(self.hdwf, c_int(self.DEVICE_ADDR), rgTX, c_int(2), byref(iNak))
        return iNak.value == 0
    
    def read_register(self,reg):
        iNak = c_int()
        rgTX = (c_ubyte * 1)(reg)
        self.dwf.FDwfDigitalI2cWrite(self.hdwf, c_int(self.DEVICE_ADDR), rgTX, c_int(1), byref(iNak))
        if iNak.value == 0:
            rgRX = (c_ubyte * 1)()
            self.dwf.FDwfDigitalI2cRead(self.hdwf, c_int(self.DEVICE_ADDR), rgRX, c_int(1), byref(iNak))
            if iNak.value == 0:
                return rgRX[0]
        return 0
    
    def supply(self,voltage):
        self.dwf.FDwfAnalogIOReset(self.hdwf)
        self.dwf.FDwfAnalogIOChannelNodeSet(self.hdwf, c_int(0), c_int(1), c_double(voltage))
        self.dwf.FDwfAnalogIOChannelNodeSet(self.hdwf, c_int(0), c_int(0), c_double(1))
        self.dwf.FDwfAnalogIOEnableSet(self.hdwf, c_int(1))
        time.sleep(0.5)
        
        vpos = c_double()
        self.dwf.FDwfAnalogIOStatus(self.hdwf)
        self.dwf.FDwfAnalogIOChannelNodeStatus(self.hdwf, c_int(0), c_int(1), byref(vpos))
        print(f"Power: +{vpos.value:.2f}V")
        
    def ad3_init_i2c(self, clk_frq, scl_pin, sda_pin, dev_addr):
        self.DEVICE_ADDR = dev_addr<<1
        self.dwf.FDwfDigitalI2cRateSet(self.hdwf, c_double(clk_frq))
        self.dwf.FDwfDigitalI2cSclSet(self.hdwf, c_int(scl_pin))
        self.dwf.FDwfDigitalI2cSdaSet(self.hdwf, c_int(sda_pin))
        iNak = c_int()
        self.dwf.FDwfDigitalI2cClear(self.hdwf, byref(iNak))


    def read_data(self, reg, length):
        iNak = c_int()
        # TX buffer = register address
        rgTX = (c_ubyte * 1)(reg)
        # RX buffer
        rgRX = (c_ubyte * length)()
        # Combined write + repeated start + read
        self.dwf.FDwfDigitalI2cWriteRead(
            self.hdwf,
            c_int(self.DEVICE_ADDR),
            rgTX,
            c_int(1),
            rgRX,
            c_int(length),
            byref(iNak)
        )
        # Check ACK status
        if iNak.value == 0:
            return list(rgRX)
        return []
        
    def close(self):
        self.dwf.FDwfDeviceCloseAll()

# %% [markdown]
# ### creating the mpu6050 class
# %%
class mpu6050:
    
    def __init__(self, supply, clk_frq, scl_pin, sda_pin):
        self.AD3 = ad3()
        self.AD3.supply(supply)
        self.AD3.ad3_init_i2c(clk_frq, scl_pin, sda_pin ,0x68)
        self.acc_addr = 0x3b
        self.gyro_addr = 0x43
        self.temp_addr = 0x41
        self.accX = 0
        self.accY = 0
        self.accZ = 0
        self.temp = 0
        self.gyroX = 0
        self.gyroY = 0
        self.gyroZ = 0
        self.saved_y = 0
        self.data = {
            'accX':[], 'accY':[], 'accZ':[],
            'temp': [],
            'gyroX':[], 'gyroY':[], 'gyroZ':[]
                }
        
    def _to_int16(self, high, low):
        value = (high << 8) | low
        if value & 0x8000: #1000 0000 0000 0000 0000 0b'1010101010101010
            value -= 0x10000
        return value
    
    def read_acc(self):
        addr=self.acc_addr
        self.accX = self._to_int16(self.AD3.read_register(addr+0), self.AD3.read_register(addr+1))
        self.accY = self._to_int16(self.AD3.read_register(addr+2), self.AD3.read_register(addr+3))
        self.accZ = self._to_int16(self.AD3.read_register(addr+4), self.AD3.read_register(addr+5))
        return np.array([self.accX,self.accY,self.accZ])

    def read_gyro(self):
        addr=self.gyro_addr
        self.gyroX = self._to_int16(self.AD3.read_register(addr+0), self.AD3.read_register(addr+1))
        self.gyroY = self._to_int16(self.AD3.read_register(addr+2), self.AD3.read_register(addr+3))
        self.gyroZ = self._to_int16(self.AD3.read_register(addr+4), self.AD3.read_register(addr+5))
        return np.array([self.gyroX,self.gyroY,self.gyroZ])

    def read_temp(self):
       addr=self.temp_addr
       self.temp = self._to_int16(self.AD3.read_register(addr+0), self.AD3.read_register(addr+1))
       
    def read(self):
        data = self.AD3.read_data(self.acc_addr, 14)
    
        if len(data) != 14:
            return False
        
            # Accelerometer
        self.accX = self._to_int16(data[0], data[1])
        self.accY = self._to_int16(data[2], data[3])
        self.accZ = self._to_int16(data[4], data[5])
    
        # Temperature
        self.temp = self._to_int16(data[6], data[7])
    
        # Gyroscope
        self.gyroX = self._to_int16(data[8], data[9])
        self.gyroY = self._to_int16(data[10], data[11])
        self.gyroZ = self._to_int16(data[12], data[13])
    
        return np.array(data)


    def get_data(self):
        self.read()
        self.data['accX'].append(self.accX)
        self.data['accY'].append(self.accY)
        self.data['accZ'].append(self.accZ)
        self.data['temp'].append(self.temp)
        self.data['gyroX'].append(self.gyroX)
        self.data['gyroY'].append(self.gyroY)
        self.data['gyroZ'].append(self.gyroZ)
        return self.data
    
    def clear_data(self):
        self.data = {
            'accX':[], 'accY':[], 'accZ':[],
            'temp': [],
            'gyroX':[], 'gyroY':[], 'gyroZ':[]
            }

# %%

def generate_value() -> float:

    # gyro_p = mpu1.gyroX
    mpu1.read()
    gyro_flt = float(0.1*mpu1.saved_y+0.9*mpu1.gyroX)/131.0
    mpu1.saved_y = gyro_flt
    return gyro_flt
    # return float(mpu1.gyroX/131.0)

# %%
# from mpu6050_wrapper import mpu6050
mpu1 = mpu6050(5, 400e3, 0, 1)

# setting DLPF for 44Hz bandwidth
mpu1.AD3.write_register(0x1a, 0x3)
# setting internal ADC sampling frequency to 100Hz
mpu1.AD3.write_register(0x19, 0x09)

# %%
mpu1.AD3.close()

# %% [markdown]
# ### Tkinter plot window setting
# %%
import collections
import tkinter as tk

import matplotlib
matplotlib.use("TkAgg")                          # force TkAgg — works everywhere
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.gridspec as gridspec

# ── config ────────────────────────────────────────────────────────────────────
QUEUE_MAX   = 40       # max items in the queue
INTERVAL_MS = 400         # ms between updates  (change to speed up / slow down)
WINDOW_TITLE = "Live Queue Monitor"

# ── data source ───────────────────────────────────────────────────────────────
# Replace generate_value() with your real source:
#   serial:  return ser.readline()
#   socket:  return sock.recv(1024)
#   file:    return float(f.readline())
_phase = 0.0

# ── state ─────────────────────────────────────────────────────────────────────
queue   = collections.deque(maxlen=QUEUE_MAX)
history = []           # full history for the bottom sparkline
tick    = [0]
running = [True]

# ── build window ──────────────────────────────────────────────────────────────
root = tk.Tk()
root.title(WINDOW_TITLE)
root.configure(bg="#1e1e2e")
root.geometry("900x900")
root.resizable(True, True)

# ── matplotlib figure ─────────────────────────────────────────────────────────
fig = plt.figure(figsize=(8.6, 5.2), facecolor="#1e1e2e")
gs  = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.35,
                        left=0.07, right=0.97, top=0.88, bottom=0.1)

ax_main = fig.add_subplot(gs[0])   # live queue window
ax_hist = fig.add_subplot(gs[1])   # full history sparkline

for ax in (ax_main, ax_hist):
    ax.set_facecolor("#12121f")
    ax.tick_params(colors="#888", labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor("#333")

ax_main.set_xlim(0, QUEUE_MAX - 1)
ax_main.set_ylim(-128, 127)
ax_main.set_title("Queue window  (last 40 values)", color="#ccc", fontsize=11, pad=8)
ax_main.set_ylabel("value", color="#888", fontsize=9)
ax_main.grid(color="#2a2a3e", linewidth=0.8)

ax_hist.set_ylim(-128, 127)
ax_hist.set_title("Full history", color="#ccc", fontsize=9, pad=4)
ax_hist.grid(color="#2a2a3e", linewidth=0.6)

line_main, = ax_main.plot([], [], color="#5b9cf6", linewidth=2.0, zorder=3)
fill_main  = ax_main.fill_between([], [], alpha=0.18, color="#5b9cf6")
dot_latest,= ax_main.plot([], [], "o", color="#f5a623", markersize=7, zorder=5)
line_hist, = ax_hist.plot([], [], color="#7ecfb3", linewidth=1.0)

# stat text in top-right
stat_text = ax_main.text(
    0.99, 0.97, "", transform=ax_main.transAxes,
    ha="right", va="top", fontsize=9, color="#ccc",
    fontfamily="monospace",
    bbox=dict(boxstyle="round,pad=0.3", facecolor="#1e1e2e", edgecolor="#444", alpha=0.8)
)

canvas = FigureCanvasTkAgg(fig, master=root)
canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 0))

# ── control bar ───────────────────────────────────────────────────────────────
bar = tk.Frame(root, bg="#1e1e2e")
bar.pack(fill=tk.X, padx=8, pady=6)

lbl_tick  = tk.Label(bar, text="tick: 0",   bg="#1e1e2e", fg="#888", font=("Courier", 10))
lbl_queue = tk.Label(bar, text="queue: 0/40", bg="#1e1e2e", fg="#888", font=("Courier", 10))
lbl_val   = tk.Label(bar, text="last: —",   bg="#1e1e2e", fg="#f5a623", font=("Courier", 10))

lbl_tick.pack(side=tk.LEFT, padx=(0, 16))
lbl_queue.pack(side=tk.LEFT, padx=(0, 16))
lbl_val.pack(side=tk.LEFT)

def toggle():
    running[0] = not running[0]
    btn_pause.config(text="Resume" if not running[0] else "Pause")

def reset():
    queue.clear()
    history.clear()
    tick[0] = 0
    global _phase
    _phase = 0.0

btn_pause = tk.Button(bar, text="Pause",  command=toggle,
                      bg="#2a2a3e", fg="#ccc", relief="flat",
                      activebackground="#3a3a5e", padx=10)
btn_reset = tk.Button(bar, text="Reset",  command=reset,
                      bg="#2a2a3e", fg="#ccc", relief="flat",
                      activebackground="#3a3a5e", padx=10)

speed_var = tk.IntVar(value=INTERVAL_MS)
lbl_speed = tk.Label(bar, text="speed (ms):", bg="#1e1e2e", fg="#888", font=("Courier", 10))
slider = tk.Scale(bar, from_=50, to=2000, orient=tk.HORIZONTAL,
                  variable=speed_var, length=130,
                  bg="#1e1e2e", fg="#ccc", troughcolor="#2a2a3e",
                  highlightthickness=0, bd=0)

btn_reset.pack(side=tk.RIGHT, padx=(4, 0))
btn_pause.pack(side=tk.RIGHT, padx=(4, 0))
slider.pack(side=tk.RIGHT)
lbl_speed.pack(side=tk.RIGHT, padx=(16, 4))

# ── update loop ───────────────────────────────────────────────────────────────

def update():

    if running[0]:
        tick[0] += 1
        # nonlocal saved_y
        # saved_y = 0
        val = generate_value()
        # gyro_flt = float(0.1*saved_y+0.9*mpu1.gyroX)/131.0
        # saved_y = gyro_flt
        queue.append(val)
        history.append(val)

        data = list(queue)
        xs   = list(range(len(data)))

        # main line
        line_main.set_data(xs, data)
        dot_latest.set_data([xs[-1]], [data[-1]])

        # shaded fill — redraw by clearing old and adding new
        global fill_main
        fill_main.remove()
        fill_main = ax_main.fill_between(xs, data, alpha=0.18, color="#5b9cf6")

        # history sparkline
        hxs = list(range(len(history)))
        line_hist.set_data(hxs, history)
        ax_hist.set_xlim(0, max(len(history) - 1, 1))

        # stats
        mn, mx, avg = min(data), max(data), sum(data) / len(data)
        stat_text.set_text(f"min {mn:.1f}  max {mx:.1f}  avg {avg:.1f}")

        # labels
        lbl_tick.config(text=f"tick: {tick[0]}")
        lbl_queue.config(text=f"queue: {len(queue)}/{QUEUE_MAX}")
        lbl_val.config(text=f"last: {val:.2f}")

        canvas.draw_idle()          # non-blocking redraw

    # reschedule — uses current slider value so speed changes take effect instantly
    root.after(speed_var.get(), update)

# seed a few values so the plot isn't empty on open
# for _ in range(8):
#     v = generate_value()
#     queue.append(v)
#     history.append(v)

root.after(100, update)
root.mainloop()


# %% [markdown]
# ### plotting fft of 256 samples at a time
# %%
mpu1.clear_data()
TOTAL_SAMPLES = 256
INTERVAL_MS = 10  # 100 Hz
start_time = time.perf_counter()

for i in range(TOTAL_SAMPLES):
    target_time = start_time + (i * (INTERVAL_MS / 1000.0))

    # Precise spin-lock wait until the exact microsecond boundary
    while time.perf_counter() < target_time:
        pass
    mpu1.get_data()

import pandas as pd

df = pd.DataFrame(mpu1.data)
df.head()

signal = df['gyroX'].to_numpy()/250.0

import numpy as np

n = len(signal)
fs = 100
signal_c = signal - np.mean(signal)
window = np.hanning(n)
signal_w = signal_c * window

fft_output = np.fft.fft(signal_w)
freq = np.fft.fftfreq(n,d=1/fs)
mag = (np.abs(fft_output)/n)*2
halfn = n//2
plot_frq = freq[:halfn]
plot_mag = mag[:halfn]

import matplotlib.pyplot as plt

plt.figure(figsize=(10, 4.5), dpi=100)
plt.plot(plot_frq, plot_mag, color='#1f77b4', linewidth=1.5)

plt.title("IMU Vibration Spectrum (MPU6050 via AD3)", fontsize=12, fontweight='bold')
plt.xlabel("Frequency (Hz)", fontsize=10)
plt.ylabel("Magnitude (°/s or g)", fontsize=10)
plt.xlim(0, 50)  # Caps perfectly at the Nyquist Frequency
plt.grid(True, linestyle='--', alpha=0.6)

plt.show()