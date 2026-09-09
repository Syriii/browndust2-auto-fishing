"""独立设置窗口；设备枚举在后台，所有 Tk 更新留在主线程。"""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from bd2_fishing.app.desktop import PREFERENCE_FIELDS


class PreferencesDialog:
    def __init__(self, parent, services, *, preview=False):
        self.services, self.preview = services, preview
        self.window = tk.Toplevel(parent)
        self.window.title("设备与时延设置")
        self.window.geometry("690x760")
        self.window.minsize(650, 720)
        self.window.transient(parent)
        self.window.grab_set()
        self.cancel_event = threading.Event()
        self._poll_id = None
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.values = {k: tk.StringVar(value=v) for k, v in services.preference_values().items()}
        self.mode = tk.StringVar(value="自动适配")
        self._sync_mode()
        self.results = queue.Queue(maxsize=1)
        self.busy = False
        self.device = None
        self.calibration = None
        self.device_text = tk.StringVar(
            value="点击检测，读取游戏客户区、所在显示器及 DPI；不发送游戏输入。"
        )
        outer = ttk.Frame(self.window, padding=16)
        outer.pack(fill="both", expand=True)
        tabs = ttk.Notebook(outer)
        tabs.pack(fill="both", expand=True)
        device = ttk.Frame(tabs, padding=14)
        timing = ttk.Frame(tabs, padding=14)
        tabs.add(device, text="窗口与分辨率")
        tabs.add(timing, text="时延与等待")
        ttk.Label(device, text="窗口适配方式").grid(row=0, column=0, sticky="w", pady=8)
        ttk.Combobox(
            device,
            textvariable=self.mode,
            values=("自动适配", "核对指定尺寸"),
            state="readonly",
            width=18,
        ).grid(row=0, column=1, sticky="w")
        rows = {"time": 0, "app": 1}
        for field in PREFERENCE_FIELDS:
            page = timing if field.section == "time" else device
            row = rows[field.section]
            rows[field.section] += 1
            ttk.Label(page, text=field.label).grid(
                row=row, column=0, sticky="w", pady=7, padx=(0, 16)
            )
            ttk.Entry(page, textvariable=self.values[field.key], width=12).grid(
                row=row, column=1, sticky="w"
            )
            ttk.Label(page, text=f"{field.minimum:g}–{field.maximum:g}", style="Hint.TLabel").grid(
                row=row, column=2, sticky="w", padx=12
            )
        ttk.Label(
            device,
            text="自动适配：每次开始读取实际客户区，识别区域按比例缩放。\n"
            "核对指定尺寸：尺寸不符时停止，避免使用错误布局。\n"
            "这里不会改变游戏分辨率或移动窗口；游戏需完整位于一块显示器内。",
            wraplength=580,
            style="Hint.TLabel",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=16)
        self.detect_button = ttk.Button(device, text="自动检测设备", command=self.detect)
        self.detect_button.grid(row=4, column=0, sticky="w")
        self.use_button = ttk.Button(
            device, text="填入检测尺寸", command=self.use_device, state="disabled"
        )
        self.use_button.grid(row=4, column=1, columnspan=2, sticky="w")
        ttk.Label(device, textvariable=self.device_text, wraplength=580, style="Hint.TLabel").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=16
        )
        ttk.Label(
            timing,
            text="检测间隔越小，检查越频繁；实际周期还包括截图和处理时间。\n"
            "按住过短可能漏键，松开后等待过长可能错过下个目标。\n"
            "这些是本机设置，不能仅凭分辨率自动推算最佳值。建议一次调整一项，再做短时验证。",
            wraplength=580,
            style="Hint.TLabel",
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=14)
        self.calibrate_button = ttk.Button(timing, text="自动校准基础间隔", command=self.calibrate)
        self.calibrate_button.grid(row=9, column=0, sticky="w")
        self.apply_calibration_button = ttk.Button(
            timing, text="填入建议值", command=self.apply_calibration, state="disabled"
        )
        self.apply_calibration_button.grid(row=9, column=1, columnspan=2, sticky="w")
        self.calibration_text = tk.StringVar(
            value="测量约 2 秒，只调整检测/反馈间隔建议；按住时间需实测。"
        )
        ttk.Label(
            timing, textvariable=self.calibration_text, wraplength=580, style="Hint.TLabel"
        ).grid(row=10, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Label(outer, text="保存后在下次开始生效；运行期间不能调整。", style="Hint.TLabel").pack(
            anchor="w", pady=12
        )
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="恢复表单默认值", command=self.defaults).pack(side="left")
        ttk.Button(buttons, text="取消", command=self.close).pack(side="right")
        ttk.Button(buttons, text="保存设置", command=self.save).pack(side="right", padx=8)

    def _sync_mode(self):
        self.mode.set(
            "自动适配" if self.values["window_size_mode"].get() == "auto" else "核对指定尺寸"
        )

    def defaults(self):
        for key, value in self.services.preference_values(defaults=True).items():
            self.values[key].set(value)
        self._sync_mode()

    def save(self):
        values = {key: value.get() for key, value in self.values.items()}
        values["window_size_mode"] = "auto" if self.mode.get() == "自动适配" else "verify"
        try:
            if self.preview:
                messagebox.showinfo("界面验证", "验证模式不保存个人配置。", parent=self.window)
                return
            self.services.save_preferences(values)
        except Exception as exc:
            messagebox.showerror("无法保存设置", str(exc), parent=self.window)
            return
        self.close()

    def close(self):
        self.cancel_event.set()
        if self._poll_id is not None:
            self.window.after_cancel(self._poll_id)
            self._poll_id = None
        self.window.destroy()

    def calibrate(self):
        if self.busy or self.preview:
            return
        self.calibration = None
        self.apply_calibration_button.configure(state="disabled")
        self.calibration_text.set("正在测量本机等待精度…")
        self._start_job("calibration", lambda: self.services.calibrate_timing(self.cancel_event))

    def apply_calibration(self):
        if self.calibration:
            for key, value in self.calibration["recommendation"].items():
                self.values[key].set(value)

    def _start_job(self, kind, action):
        self.busy = True
        self.detect_button.configure(state="disabled")
        self.calibrate_button.configure(state="disabled")

        def inspect():
            try:
                result = action()
            except Exception as exc:
                result = str(exc)
            self.results.put_nowait((kind, result))

        threading.Thread(target=inspect, name="device-inspector", daemon=True).start()
        self._poll_id = self.window.after(80, self._poll)

    def detect(self):
        if self.busy:
            return
        if self.preview:
            self.device_text.set("界面验证模式不连接游戏。")
            return
        self.device = None
        self.use_button.configure(state="disabled")
        self.device_text.set("正在检测游戏窗口与显示器…")

        self._start_job("device", self.services.inspect_device)

    def _poll(self):
        self._poll_id = None
        try:
            kind, result = self.results.get_nowait()
        except queue.Empty:
            self._poll_id = self.window.after(80, self._poll)
            return
        self.busy = False
        self.detect_button.configure(state="normal")
        self.calibrate_button.configure(state="normal")
        if kind == "calibration":
            if isinstance(result, str):
                self.calibration_text.set(result)
            else:
                self.calibration = result
                recommendation = result["recommendation"]
                self.calibration_text.set(
                    (
                        f"建议检测 {recommendation['loop_sleep_seconds']}ms、反馈 {recommendation['feedback_poll_seconds']}ms。\n"
                        if recommendation
                        else ""
                    )
                    + result["reason"]
                    + "\n"
                    + result["limitation"]
                )
                if recommendation:
                    self.apply_calibration_button.configure(state="normal")
            return
        if isinstance(result, str):
            self.device_text.set(result)
        else:
            self.device = result
            self.device_text.set(
                f"客户区：{result['width']} × {result['height']}；位置：{result['position']}\n"
                f"显示器：{result['display']}；边界：{result['display_bounds']}\n"
                f"窗口 DPI：{result['dpi']}；缩放：{result['scale_percent']}%\n"
                + "\n".join(
                    f"等待 {s['requested_ms']}ms：本机中位数 {s['median_ms']}ms，最大 {s['max_ms']}ms"
                    for s in result["wait_precision"]
                )
                + "\n等待精度是后台线程样本，不代表游戏响应。最佳按键参数仍需实测。"
            )
            self.use_button.configure(state="normal")

    def use_device(self):
        if self.device:
            self.values["expected_window_width"].set(str(self.device["width"]))
            self.values["expected_window_height"].set(str(self.device["height"]))
