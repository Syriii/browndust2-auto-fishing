"""嵌入式设置页；草稿留在主线程，设备检测和校准在后台执行。"""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from bd2_fishing.app.desktop import PREFERENCE_FIELDS
from bd2_fishing.ui.scrolling import ScrollablePage


class PreferencesPage(ttk.Frame):
    def __init__(self, parent, services, *, preview=False, on_saved=None):
        super().__init__(parent, style="Card.TFrame")
        self.services, self.preview, self.on_saved = services, preview, on_saved
        self.window = self.winfo_toplevel()
        self.cancel_event = threading.Event()
        self._poll_id = None
        self.locked = False
        self.disposed = False
        self.values = {k: tk.StringVar(value=v) for k, v in services.preference_values().items()}
        self.reference_values = services.preference_values(defaults=True)
        self.mode = tk.StringVar(value="自动适配")
        self._sync_mode()
        self.detail_log = tk.BooleanVar(
            value=services.load_settings().getboolean(
                "diagnostics", "qte_detail_log", fallback=False
            )
        )
        self.saved = self._form()
        self.notice = tk.StringVar(value="设置已保存 · 下次开始任务时生效")
        self.suggestions, self.suggestion_labels, self.entries = {}, {}, {}
        self.results = queue.Queue(maxsize=1)
        self.busy = False
        self.device = self.calibration = None
        self.device_text = tk.StringVar(value="检测客户区尺寸、显示器与缩放，不发送游戏输入。")
        self.calibration_text = tk.StringVar(
            value="约 2 秒；提供本机检测与反馈间隔建议，按键时间仍需实测。"
        )
        self.page = ScrollablePage(self)
        self.page.pack(fill="both", expand=True)
        body = self.page.body
        body.columnconfigure(0, weight=1)
        device = self._section(body, "窗口与分辨率", 0)
        self._columns(device)
        ttk.Label(device, text="窗口适配方式").grid(row=1, column=0, sticky="w", pady=6)
        self.mode_box = ttk.Combobox(
            device,
            textvariable=self.mode,
            values=("自动适配", "核对指定尺寸"),
            state="readonly",
            width=12,
        )
        self.mode_box.grid(row=1, column=1, sticky="w", padx=(0, 16))
        ttk.Label(device, text="推荐：自动适配", style="Advice.TLabel").grid(
            row=1, column=2, sticky="w"
        )
        for row, field in enumerate((f for f in PREFERENCE_FIELDS if f.section == "app"), 2):
            self._field(device, row, field)
        self.detect_button = ttk.Button(device, text="检测窗口", command=self.detect)
        self.detect_button.grid(row=4, column=0, sticky="w", pady=(12, 8))
        self.use_button = ttk.Button(
            device, text="采用检测尺寸", command=self.use_device, state="disabled"
        )
        self.use_button.grid(row=4, column=1, columnspan=3, sticky="w")
        ttk.Label(device, textvariable=self.device_text, style="Hint.TLabel", wraplength=780).grid(
            row=5, column=0, columnspan=4, sticky="ew", pady=(0, 8)
        )
        ttk.Label(
            device,
            text="自动适配按客户区缩放识别区域；核对尺寸不符时停止。此处不会更改游戏分辨率。",
            style="Hint.TLabel",
            wraplength=780,
        ).grid(row=6, column=0, columnspan=4, sticky="ew")
        timing = self._section(body, "QTE 时延", 1)
        self._columns(timing)
        time_fields = [f for f in PREFERENCE_FIELDS if f.section == "time"]
        for row, field in enumerate(time_fields[:4], 1):
            self._field(timing, row, field)
        self.calibrate_button = ttk.Button(timing, text="校准本机间隔", command=self.calibrate)
        self.calibrate_button.grid(row=5, column=0, sticky="w", pady=(12, 8))
        self.apply_calibration_button = ttk.Button(
            timing, text="采用校准建议", command=self.apply_calibration, state="disabled"
        )
        self.apply_calibration_button.grid(row=5, column=1, columnspan=3, sticky="w")
        ttk.Label(
            timing, textvariable=self.calibration_text, style="Hint.TLabel", wraplength=780
        ).grid(row=6, column=0, columnspan=4, sticky="ew")
        self.advanced_button = ttk.Button(
            body, text="▸ 页面等待与诊断", command=self.toggle_advanced
        )
        self.advanced_button.grid(row=2, column=0, sticky="w", pady=(8, 12))
        self.advanced = ttk.Frame(body, style="Card.TFrame")
        self.advanced.bind("<Configure>", self._wrap_notes)
        self.advanced.grid(row=3, column=0, sticky="ew")
        self._columns(self.advanced)
        for row, field in enumerate(time_fields[4:], 1):
            self._field(self.advanced, row, field)
        self.trace_check = ttk.Checkbutton(
            self.advanced, text="记录逐帧诊断", variable=self.detail_log
        )
        self.trace_check.grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 6))
        ttk.Label(
            self.advanced,
            text="失败与异常截图始终自动保存，无需开启逐帧诊断。",
            style="Hint.TLabel",
            wraplength=700,
        ).grid(row=6, column=0, columnspan=4, sticky="w")
        self.advanced.grid_remove()
        ttk.Label(self, textvariable=self.notice, style="Hint.TLabel", wraplength=520).pack(
            fill="x", padx=20, pady=(4, 0), side="bottom"
        )
        footer = ttk.Frame(self, padding=(20, 12), style="Card.TFrame")
        footer.pack(fill="x")
        self.save_button = ttk.Button(
            footer, text="保存设置", style="Start.TButton", command=self.save
        )
        self.save_button.pack(side="right")
        self.discard_button = ttk.Button(footer, text="撤销更改", command=self.discard)
        self.discard_button.pack(side="right", padx=8)
        self.default_button = ttk.Button(footer, text="恢复默认", command=self.defaults)
        self.default_button.pack(side="right")
        for variable in (*self.values.values(), self.mode, self.detail_log):
            variable.trace_add("write", self._changed)

    def _section(self, parent, title, row):
        section = ttk.LabelFrame(parent, text=title, padding=12)
        section.grid(row=row, column=0, sticky="ew", pady=(0, 16))
        section.bind("<Configure>", self._wrap_notes)
        return section

    def _wrap_notes(self, event):
        for widget in event.widget.winfo_children():
            if isinstance(widget, ttk.Label) and int(widget.grid_info().get("columnspan", 1)) > 1:
                width = max(180, event.width - 24)
                if int(widget.cget("wraplength") or 0) != width:
                    widget.configure(wraplength=width)

    def _columns(self, parent):
        parent.columnconfigure(2, weight=1)
        for col, title in enumerate(("设置项 / 允许范围", "当前值", "建议 / 参考")):
            ttk.Label(parent, text=title, style="Hint.TLabel").grid(
                row=0, column=col, sticky="w", padx=(0, 10), pady=(0, 6)
            )

    def _field(self, parent, row, field):
        caption = ttk.Frame(parent, style="Card.TFrame")
        caption.grid(row=row, column=0, sticky="w", pady=5, padx=(0, 10))
        label_text = (
            field.label.replace("QTE ", "")
            .replace("预期客户区", "客户区")
            .replace("（毫秒）", "（ms）")
            .replace("（像素）", "（px）")
        )
        ttk.Label(caption, text=label_text).pack(anchor="w")
        ttk.Label(
            caption, text=f"范围 {field.minimum:g}–{field.maximum:g}", style="Hint.TLabel"
        ).pack(anchor="w")
        entry = ttk.Entry(parent, textvariable=self.values[field.key], width=10)
        entry.grid(row=row, column=1, sticky="w", padx=(0, 10))
        self.entries[field.key] = entry
        suggestion = tk.StringVar(value=self._reference_text(field.key))
        self.suggestions[field.key] = suggestion
        label = ttk.Label(parent, textvariable=suggestion, style="Advice.TLabel", wraplength=145)
        label.grid(row=row, column=2, sticky="w", padx=(0, 14))
        self.suggestion_labels[field.key] = label

    def _form(self):
        values = {key: value.get() for key, value in self.values.items()}
        values["window_size_mode"] = "auto" if self.mode.get() == "自动适配" else "verify"
        values["qte_detail_log"] = self.detail_log.get()
        return values

    @property
    def dirty(self):
        return self._form() != self.saved

    def _changed(self, *args):
        if not self.locked:
            self.notice.set("有未保存的更改" if self.dirty else "设置已保存 · 下次开始任务时生效")

    def toggle_advanced(self):
        opened = bool(self.advanced.winfo_manager())
        if opened:
            self.advanced.grid_remove()
        else:
            self.advanced.grid()
        self.advanced_button.configure(text=("▸" if opened else "▾") + " 页面等待与诊断")

    def set_locked(self, locked):
        if self.locked == locked:
            return
        self.locked = locked
        state = "disabled" if locked else "normal"
        for widget in (
            *self.entries.values(),
            self.trace_check,
            self.save_button,
            self.discard_button,
            self.default_button,
        ):
            widget.configure(state=state)
        self.mode_box.configure(state="disabled" if locked else "readonly")
        self._job_buttons()
        if locked:
            self.notice.set("运行中仅可查看 · 停止任务后可修改")
        else:
            self._changed()

    def _job_buttons(self):
        blocked = self.busy or self.locked or self.disposed
        for button in (self.detect_button, self.calibrate_button):
            button.configure(state="disabled" if blocked else "normal")
        self.use_button.configure(state="normal" if self.device and not blocked else "disabled")
        self.apply_calibration_button.configure(
            state="normal"
            if self.calibration and self.calibration.get("recommendation") and not blocked
            else "disabled"
        )

    def discard(self):
        if self.locked:
            return
        for key, value in self.saved.items():
            if key in self.values:
                self.values[key].set(value)
        self.detail_log.set(self.saved["qte_detail_log"])
        self._sync_mode()
        self._changed()

    def _reference_text(self, key):
        if key.startswith("expected_window_"):
            return "检测后显示客户区尺寸"
        value = self.reference_values[key]
        suffix = " · 需实测" if key in {"qte_hold_seconds", "qte_settle_seconds"} else ""
        return f"默认 {value}{suffix}"

    def _sync_mode(self):
        self.mode.set(
            "自动适配" if self.values["window_size_mode"].get() == "auto" else "核对指定尺寸"
        )

    def defaults(self):
        if self.locked:
            return
        for key, value in self.services.preference_values(defaults=True).items():
            self.values[key].set(value)
        self._sync_mode()
        self.detail_log.set(False)

    def save(self):
        if self.locked or self.busy:
            return False
        values = {key: value.get() for key, value in self.values.items()}
        values["window_size_mode"] = "auto" if self.mode.get() == "自动适配" else "verify"
        try:
            if self.preview:
                messagebox.showinfo("界面验证", "验证模式不保存个人配置。", parent=self.window)
                return
            self.services.save_preferences(values, detail_log=self.detail_log.get())
        except Exception as exc:
            messagebox.showerror("无法保存设置", str(exc), parent=self.window)
            return
        self.saved = self._form()
        self._changed()
        if self.on_saved:
            self.on_saved()
        return True

    def close(self):
        self.disposed = True
        self.cancel_event.set()
        if self._poll_id is not None:
            self.window.after_cancel(self._poll_id)
            self._poll_id = None

    def calibrate(self):
        if self.busy or self.locked or self.preview:
            return
        self.calibration = None
        for key in ("loop_sleep_seconds", "feedback_poll_seconds"):
            self.suggestions[key].set(self._reference_text(key))
        self.apply_calibration_button.configure(state="disabled")
        self.calibration_text.set("正在测量本机等待精度…")
        self._start_job("calibration", lambda: self.services.calibrate_timing(self.cancel_event))

    def apply_calibration(self):
        if self.calibration and not self.locked and not self.busy:
            for key, value in self.calibration["recommendation"].items():
                self.values[key].set(value)

    def _start_job(self, kind, action):
        self.busy = True
        self._job_buttons()

        def inspect():
            try:
                result = action()
            except Exception as exc:
                result = str(exc)
            self.results.put_nowait((kind, result))

        threading.Thread(target=inspect, name="device-inspector", daemon=True).start()
        self._poll_id = self.window.after(80, self._poll)

    def detect(self):
        if self.busy or self.locked:
            return
        if self.preview:
            self.device_text.set("界面验证模式不连接游戏。")
            return
        self.device = None
        for key in ("expected_window_width", "expected_window_height"):
            self.suggestions[key].set(self._reference_text(key))
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
        if kind == "calibration":
            if isinstance(result, str):
                self.calibration_text.set(result)
            else:
                self.calibration = result
                recommendation = result["recommendation"]
                for key, value in recommendation.items():
                    self.suggestions[key].set(f"本机建议 {value} ms")
                measurements = "；".join(
                    f"{row['requested_ms']}ms：p95 {row['p95_ms']}ms / 最大 {row['max_ms']}ms"
                    for row in result.get("waits", [])
                )
                self.calibration_text.set(
                    "\n".join(
                        text
                        for text in (measurements, result["reason"], result["limitation"])
                        if text
                    )
                )
                if recommendation:
                    self.apply_calibration_button.configure(state="normal")
            self._job_buttons()
            return
        if isinstance(result, str):
            self.device_text.set(result)
        else:
            self.device = result
            self.suggestions["expected_window_width"].set(f"实测 {result['width']} px")
            self.suggestions["expected_window_height"].set(f"实测 {result['height']} px")
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
        self._job_buttons()

    def use_device(self):
        if self.device and not self.locked and not self.busy:
            self.values["expected_window_width"].set(str(self.device["width"]))
            self.values["expected_window_height"].set(str(self.device["height"]))
