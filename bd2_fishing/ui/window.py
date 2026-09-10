"""ui.window：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging
import tkinter as tk
from collections import deque
from tkinter import messagebox, ttk

from bd2_fishing.app.desktop import DesktopServices, FishingLocation
from bd2_fishing.runtime import control as run_control
from bd2_fishing.ui.logs import UILogHandler
from bd2_fishing.ui.preferences import PreferencesPage
from bd2_fishing.ui.theme import ACCENT, FONT, apply_icon, apply_theme, center_window
from bd2_fishing.ui.updates import UpdatePanel

log = logging.getLogger(__name__)


class FishingApp:
    def __init__(self, root, target, *, preview=False, services=None):
        self.root, self.target, self.preview = root, target, preview
        self.services = services or DesktopServices(read_only=preview)
        self.config_path = self.services.config_path
        config = self.services.load_settings()
        self.snapshot = config
        self.selected_location = None
        self.closing = False
        self.preferences = None
        self.records = deque(maxlen=1500)
        self.diagnostic_records = deque(maxlen=500)
        self._last_log_key = None
        self.settings_visible = False
        self.handler = UILogHandler()
        self.controller = self.services.create_task(self._run, preview=preview)
        self.status = tk.StringVar(value="待机")
        self.detail = tk.StringVar(value="点击开始，自动聚焦游戏后运行。")
        self.issue = tk.StringVar(value="暂无警告或错误")
        self.location = tk.StringVar(value=config.get("app", "location", fallback="自动识别"))
        valid_locations = ["自动识别"] + [item.value for item in FishingLocation]
        if self.location.get() not in valid_locations:
            self.location.set("自动识别")
        self.auto_clear = tk.BooleanVar(
            value=config.getboolean("backpack", "auto_clear_enabled", fallback=True)
        )
        self.awake = tk.BooleanVar(value=config.getboolean("app", "prevent_sleep", fallback=False))
        self.level = tk.StringVar(value="运行信息")
        self.follow = tk.BooleanVar(value=True)
        self._build(valid_locations)
        self.updates = UpdatePanel(self)
        logging.getLogger().addHandler(self.handler)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self._callback_error
        log.info("界面已就绪；点击开始钓鱼或停止任务控制运行")
        for message in getattr(self.services, "startup_messages", []):
            log.info(message)
        if preview:
            log.info("界面验证模式：不聚焦游戏，不发送按键，不保存配置")
        self._poll_id = self.root.after(50, self._poll)

    def _build(self, locations):
        root = self.root
        root.title("BD2 自动钓鱼" + (" · 界面验证" if self.preview else ""))
        scale = root.winfo_fpixels("1i") / 96
        root.geometry(f"{round(1040 * scale)}x{round(720 * scale)}")
        root.minsize(round(960 * scale), round(640 * scale))
        apply_theme(root)
        self.brand_icon = apply_icon(root)
        outer = ttk.Frame(root, padding=18)
        outer.pack(fill="both", expand=True)
        run = ttk.Frame(outer)
        run.pack(fill="both", expand=True)
        run.rowconfigure(0, weight=1)
        run.columnconfigure(1, weight=1)
        left = ttk.Frame(run, style="Card.TFrame", padding=18)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(9, weight=1)
        ttk.Label(left, text="钓鱼任务", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 18)
        )
        ttk.Label(left, text="当前钓场", style="Hint.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 6)
        )
        self.location_box = ttk.Combobox(
            left, values=locations, textvariable=self.location, state="readonly", width=23
        )
        self.location_box.grid(row=2, column=0, sticky="ew", pady=(0, 18))
        self.clear_check = ttk.Checkbutton(left, text="满包时自动清理", variable=self.auto_clear)
        self.clear_check.grid(row=3, column=0, sticky="w", pady=(0, 6))
        self.awake_check = ttk.Checkbutton(left, text="运行时保持唤醒", variable=self.awake)
        self.awake_check.grid(row=4, column=0, sticky="w")
        ttk.Separator(left).grid(row=5, column=0, sticky="ew", pady=20)
        ttk.Label(left, text="本机参数", style="Section.TLabel").grid(
            row=6, column=0, sticky="w", pady=(0, 8)
        )
        self.parameter_summary = tk.StringVar()
        self.summary_label = ttk.Label(
            left, textvariable=self.parameter_summary, style="Hint.TLabel", wraplength=230
        )
        self.summary_label.grid(row=7, column=0, sticky="w")
        self.preferences_button = ttk.Button(
            left, text="设备与时延设置", command=self.toggle_preferences
        )
        self.preferences_button.grid(row=8, column=0, sticky="ew", pady=(12, 0))
        self.action_button = ttk.Button(
            left, text="▶ 开始钓鱼", style="Start.TButton", command=self.toggle_task
        )
        ttk.Label(left, textvariable=self.status, style="Hint.TLabel").grid(
            row=9, column=0, sticky="sw", pady=(12, 0)
        )
        self.action_button.grid(row=10, column=0, sticky="ew", pady=(8, 8))
        self.deck = ttk.Frame(run, style="Card.TFrame")
        self.deck.grid(row=0, column=1, sticky="nsew")
        self.deck.rowconfigure(0, weight=1)
        self.deck.columnconfigure(0, weight=1)
        self.run_panel = panel = ttk.Frame(self.deck, style="Card.TFrame", padding=18)
        panel.grid(row=0, column=0, sticky="nsew")
        ttk.Label(panel, text="当前状态", style="Hint.TLabel").pack(anchor="w")
        self.status_label = ttk.Label(
            panel, textvariable=self.status, foreground=ACCENT, font=(FONT, 18, "bold")
        )
        self.status_label.pack(anchor="w", pady=(4, 6))
        self.detail_label = ttk.Label(
            panel, textvariable=self.detail, style="Hint.TLabel", wraplength=550
        )
        self.detail_label.pack(fill="x")
        ttk.Separator(panel).pack(fill="x", pady=16)
        toolbar = ttk.Frame(panel, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="运行记录", style="Section.TLabel").pack(side="left")
        ttk.Checkbutton(toolbar, text="自动滚动", variable=self.follow).pack(side="right")
        selector = ttk.Combobox(
            toolbar,
            textvariable=self.level,
            values=["运行信息", "警告 / 错误", "详细诊断"],
            state="readonly",
            width=12,
        )
        selector.pack(side="left", padx=14)
        selector.bind("<<ComboboxSelected>>", lambda _: self._render())
        text_frame = ttk.Frame(panel, style="Card.TFrame")
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(
            text_frame,
            bg="#f5f8fa",
            fg="#344c57",
            relief="flat",
            wrap="word",
            font=(FONT, 9),
            padx=12,
            pady=10,
            state="disabled",
            height=1,
            width=1,
            selectbackground="#c8e6e1",
            highlightthickness=0,
            spacing1=2,
        )
        scroll = ttk.Scrollbar(text_frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("WARNING", foreground="#a2600e")
        self.text.tag_configure("ERROR", foreground="#b52f38")
        self.text.tag_configure("DEBUG", foreground="#677b91")
        self.issue_label = ttk.Label(
            panel, textvariable=self.issue, wraplength=550, style="Hint.TLabel"
        )
        self.issue_label.pack(fill="x", pady=(8, 0))
        links = ttk.Frame(panel, style="Card.TFrame")
        links.pack(fill="x", pady=(10, 0))
        ttk.Button(links, text="日志目录", command=self.open_logs).pack(side="left")
        ttk.Button(links, text="异常截图", command=self.services.open_screenshot_directory).pack(
            side="left", padx=8
        )
        self.update_button = ttk.Button(
            links, text="更新与存储", command=lambda: self.updates.open()
        )
        self.update_button.pack(side="right")
        panel.bind("<Configure>", self._resize_details)
        self.preferences = PreferencesPage(
            self.deck, self.services, preview=self.preview, on_saved=self._settings_saved
        )
        self.preferences.grid(row=0, column=0, sticky="nsew")
        self.preferences.grid_remove()
        self.detail_log = self.preferences.detail_log
        self.trace_check = self.preferences.trace_check
        self._settings_saved()
        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Label(
            footer, text="失败与异常自动留图 · 运行时请保持游戏前台可见", style="PageHint.TLabel"
        ).pack(side="left")
        self.log_notice = tk.StringVar(value="保留 1500 条进展 · 更多诊断见日志文件")
        ttk.Label(footer, textvariable=self.log_notice, style="PageHint.TLabel").pack(side="right")
        center_window(root, self.services)

    def _resize_details(self, event):
        width = max(160, event.width - 36)
        self.detail_label.configure(wraplength=width)
        self.issue_label.configure(wraplength=width)

    def _settings_saved(self):
        values = self.services.preference_values()
        mode = (
            "自动适配窗口"
            if values["window_size_mode"] == "auto"
            else (f"核对 {values['expected_window_width']} × {values['expected_window_height']}")
        )
        self.parameter_summary.set(
            f"{mode}\n检测 {values['loop_sleep_seconds']} ms · "
            f"按住 {values['qte_hold_seconds']} ms\n松开等待 {values['qte_settle_seconds']} ms"
        )

    def start(self):
        if self.closing or self.controller.running:
            return
        if self.updates.busy:
            self.detail.set("正在检查更新或维护存储，请等待完成。")
            return
        if self.preferences.busy:
            self.detail.set("设备检测或校准进行中，请等待完成。")
            return
        if self.preferences.dirty:
            self.open_preferences()
            self.preferences.notice.set("请先保存或撤销更改，再开始任务")
            return
        try:
            if not self.preview:
                self.snapshot = self.services.save_settings(
                    {
                        "backpack": {"auto_clear_enabled": str(self.auto_clear.get()).lower()},
                        "diagnostics": {
                            "qte_detail_log": str(self.detail_log.get()).lower(),
                        },
                        "app": {
                            "location": self.location.get(),
                            "prevent_sleep": str(self.awake.get()).lower(),
                        },
                    }
                )
            self.selected_location = (
                None if self.location.get() == "自动识别" else FishingLocation(self.location.get())
            )
            self.controller.start()
            self.preferences.set_locked(self.controller.running)
        except Exception as exc:
            log.exception("无法开始任务")
            self.controller.last_error = str(exc)

    def _run(self):
        self.target(self.snapshot, location=self.selected_location, interactive=False)

    def stop(self):
        self.controller.stop()

    def toggle_task(self):
        if self.controller.running:
            if not self.controller.control.stopped.is_set():
                self.stop()
        else:
            self.start()

    def close(self):
        if self.closing:
            return
        if self.preferences.dirty and not messagebox.askyesno(
            "尚未保存", "退出并放弃未保存的设置？", parent=self.root
        ):
            return
        self.closing = True
        self.updates.close()
        self.preferences.close()
        self.stop()

    def _poll(self):
        self._poll_id = None
        self._consume_logs()
        if self._refresh_task_state():
            self._poll_id = self.root.after(80, self._poll)

    def _consume_logs(self):
        pending = self.handler.drain()
        for entry in pending:
            target = (
                self.records
                if entry.level >= logging.INFO and not entry.diagnostic_only
                else self.diagnostic_records
            )
            target.append(entry)
            if entry.level >= logging.WARNING and not entry.diagnostic_only:
                self.issue.set("最近提示：" + entry.message.splitlines()[0][:170])
        if pending:
            self._append(pending)

    def _refresh_task_state(self):
        active = self.controller.running
        state = "disabled" if active or self.closing else "normal"
        stopping = active and self.controller.control.stopped.is_set()
        self.action_button.configure(
            text="正在停止…" if stopping else "■ 停止任务" if active else "▶ 开始钓鱼",
            style="Stop.TButton" if active else "Start.TButton",
            state="disabled"
            if self.closing
            or stopping
            or (not active and (self.preferences.busy or self.updates.busy))
            else "normal",
        )
        self.preferences.set_locked(active or self.closing or self.updates.busy)
        for widget in (self.clear_check, self.awake_check):
            widget.configure(state=state)
        self.location_box.configure(state="disabled" if active or self.closing else "readonly")
        return self._refresh_status(active)

    def _refresh_status(self, active):
        if self.closing:
            self.status.set("正在关闭")
            self.detail.set("等待当前操作退出并释放按键、截图和电源请求…")
            if not active:
                logging.getLogger().removeHandler(self.handler)
                self.root.destroy()
                return False
        elif active:
            stopping = self.controller.control.stopped.is_set()
            self.status.set("正在停止" if stopping else self.controller.control.phase)
            self.detail.set("点击停止任务结束运行；切离游戏、锁屏或移动窗口也会停止任务。")
        else:
            self.status.set("需要处理" if self.controller.last_error else "待机")
            self.detail.set(
                (
                    "任务发生错误，请查看下方运行记录；诊断详情可在日志筛选中查看。"
                    if self.controller.last_error
                    else ""
                )
                or self.controller.last_stop_reason
                or "点击开始，自动聚焦游戏后运行。"
            )
        return True

    def _render(self):
        position = self.text.yview()[0]
        self._last_log_key = None
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self._append(
            sorted(
                (*self.records, *self.diagnostic_records),
                key=lambda entry: (entry.created, entry.sequence),
            )
        )
        if not self.follow.get():
            self.text.yview_moveto(position)

    def _append(self, records):
        minimum = {
            "运行信息": logging.INFO,
            "警告 / 错误": logging.WARNING,
            "详细诊断": logging.DEBUG,
        }[self.level.get()]
        records = [
            entry
            for entry in records
            if entry.level >= minimum
            and (not entry.diagnostic_only or self.level.get() == "详细诊断")
        ]
        # 警告优先出队；迟到的诊断在主线程合并回原时间位置，不能追加到新警告之后。
        if records and self._last_log_key is not None:
            if (records[0].created, records[0].sequence) < self._last_log_key:
                self._render()
                return
        position = self.text.yview()[0]
        self.text.configure(state="normal")
        for entry in records:
            level = entry.level
            tag = (
                "ERROR"
                if level >= logging.ERROR
                else "WARNING"
                if level >= logging.WARNING
                else "DEBUG"
                if level < logging.INFO
                else "INFO"
            )
            self.text.insert(
                "end", entry.display(self.level.get() == "详细诊断")[:5000] + "\n", tag
            )
            self._last_log_key = (entry.created, entry.sequence)
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > 2000:
            self.text.delete("1.0", f"{lines - 2000}.0")
        if self.handler.skipped:
            self.log_notice.set(f"已跳过 {self.handler.skipped} 条展示副本 · 更多诊断见日志文件")
        self.text.configure(state="disabled")
        if self.follow.get():
            self.text.see("end")
        else:
            self.text.yview_moveto(position)

    def open_logs(self):
        self.services.open_log_directory()

    def open_preferences(self):
        if not self.closing:
            self.run_panel.grid_remove()
            self.preferences.grid()
            self.settings_visible = True
            self.preferences_button.configure(text="← 返回运行记录")

    def open_run(self):
        self.preferences.grid_remove()
        self.run_panel.grid()
        self.settings_visible = False
        self.preferences_button.configure(text="设备与时延设置")

    def toggle_preferences(self):
        if self.settings_visible:
            self.open_run()
        else:
            self.open_preferences()

    def _callback_error(self, exc_type, exc, tb):
        log.error("界面操作异常", exc_info=(exc_type, exc, tb))
        self.controller.last_error = str(exc)


def launch(target, *, preview=False, services=None):
    if preview:

        def target(*args, **kwargs):
            run_control.set_status("模拟任务运行中")
            log.info("模拟任务开始：不连接游戏")
            run_control.sleep(180)

    root = tk.Tk()
    try:
        FishingApp(root, target, preview=preview, services=services)
    except Exception as exc:
        log.exception("程序页面初始化失败")
        messagebox.showerror(
            "无法打开程序", f"{exc}\n\n详细信息见运行目录的 logs/auto_fishing.log", parent=root
        )
        root.destroy()
        return
    root.mainloop()
