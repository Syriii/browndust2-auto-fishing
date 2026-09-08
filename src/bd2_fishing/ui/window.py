"""ui.window：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging
import os
import queue
import tkinter as tk
from collections import deque
from tkinter import messagebox, ttk

from bd2_fishing.app.desktop import DesktopServices, FishingLocation
from bd2_fishing.runtime import control as run_control

log = logging.getLogger(__name__)


class UILogHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.messages = queue.Queue(maxsize=2000)
        self.skipped = 0
        self.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record):
        try:
            self.messages.put_nowait((record.levelno, self.format(record)))
        except queue.Full:
            # 仅丢弃界面展示副本；项目文件处理器仍完整接收此记录。
            self.skipped += 1
        except Exception:
            self.handleError(record)


class FishingApp:
    def __init__(self, root, target, *, preview=False, services=None):
        self.root, self.target, self.preview = root, target, preview
        self.services = services or DesktopServices()
        self.config_path = self.services.config_path
        config = self.services.load_settings()
        self.snapshot = config
        self.selected_location = None
        self.closing = False
        self.records = deque(maxlen=1500)
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
        self.detail_log = tk.BooleanVar(
            value=config.getboolean("diagnostics", "qte_detail_log", fallback=False)
        )
        self.feedback = tk.BooleanVar(
            value=config.getboolean("diagnostics", "qte_feedback_enabled", fallback=True)
        )
        self.level = tk.StringVar(value="运行信息")
        self.follow = tk.BooleanVar(value=True)
        self._build(valid_locations)
        logging.getLogger().addHandler(self.handler)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self._callback_error
        log.info("界面已就绪；点击开始钓鱼或停止任务控制运行")
        if preview:
            log.info("界面验证模式：不聚焦游戏，不发送按键，不保存配置")
        self.root.after(50, self._poll)

    def _build(self, locations):
        root = self.root
        root.title("BD2 自动钓鱼" + (" · 界面验证" if self.preview else ""))
        root.geometry("860x720")
        root.minsize(760, 640)
        root.configure(bg="#eef2f6")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef2f6")
        style.configure("Card.TFrame", background="white")
        style.configure(
            "TLabel", background="white", foreground="#253249", font=("Microsoft YaHei UI", 10)
        )
        style.configure("Hint.TLabel", foreground="#627087", font=("Microsoft YaHei UI", 9))
        style.configure("TCheckbutton", background="white", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(14, 8))
        style.configure(
            "Start.TButton",
            background="#117568",
            foreground="white",
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        style.map("Start.TButton", background=[("disabled", "#ccd6da"), ("active", "#0c6258")])
        outer = ttk.Frame(root, padding=22)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 14))
        tk.Label(
            header,
            text="BD2 自动钓鱼",
            bg="#eef2f6",
            fg="#162b42",
            font=("Microsoft YaHei UI", 21, "bold"),
        ).pack(side="left")

        card = ttk.Frame(outer, style="Card.TFrame", padding=18)
        card.pack(fill="x", pady=(0, 12))
        self.status_label = ttk.Label(
            card, textvariable=self.status, font=("Microsoft YaHei UI", 15, "bold")
        )
        self.status_label.pack(anchor="w")
        ttk.Label(card, textvariable=self.detail, style="Hint.TLabel", wraplength=760).pack(
            anchor="w", pady=(5, 12)
        )
        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.pack(fill="x")
        self.start_button = ttk.Button(
            buttons, text="开始钓鱼", style="Start.TButton", command=self.start
        )
        self.start_button.pack(side="left", padx=(0, 10))
        self.stop_button = ttk.Button(buttons, text="停止任务", command=self.stop, state="disabled")
        self.stop_button.pack(side="left")
        ttk.Label(buttons, text="游戏需保持前台可见；锁屏后无法继续", style="Hint.TLabel").pack(
            side="right"
        )

        settings = ttk.Frame(outer, style="Card.TFrame", padding=16)
        settings.pack(fill="x", pady=(0, 12))
        ttk.Label(settings, text="钓场").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.location_box = ttk.Combobox(
            settings, values=locations, textvariable=self.location, state="readonly", width=17
        )
        self.location_box.grid(row=0, column=1, sticky="w", padx=(0, 22))
        self.clear_check = ttk.Checkbutton(
            settings, text="满包时自动清理", variable=self.auto_clear
        )
        self.clear_check.grid(row=0, column=2, sticky="w")
        self.awake_check = ttk.Checkbutton(
            settings, text="运行时防止自动息屏 / 睡眠", variable=self.awake
        )
        self.awake_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.trace_check = ttk.Checkbutton(
            settings, text="逐帧诊断写入文件", variable=self.detail_log
        )
        self.trace_check.grid(row=1, column=2, sticky="w", pady=(12, 0))
        self.feedback_check = ttk.Checkbutton(
            settings, text="记录 QTE 结果、失败截图和鱼获结算", variable=self.feedback
        )
        self.feedback_check.grid(row=2, column=0, columnspan=3, sticky="w", pady=(12, 0))

        panel = ttk.Frame(outer, style="Card.TFrame", padding=16)
        panel.pack(fill="both", expand=True)
        toolbar = ttk.Frame(panel, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Label(toolbar, text="运行日志", font=("Microsoft YaHei UI", 11, "bold")).pack(
            side="left"
        )
        selector = ttk.Combobox(
            toolbar,
            textvariable=self.level,
            values=["运行信息", "警告 / 错误", "详细诊断"],
            state="readonly",
            width=13,
        )
        selector.pack(side="left", padx=14)
        selector.bind("<<ComboboxSelected>>", lambda _: self._render())
        ttk.Checkbutton(toolbar, text="自动滚动", variable=self.follow).pack(side="left")
        ttk.Button(toolbar, text="打开日志目录", command=self.open_logs).pack(side="right")
        text_frame = ttk.Frame(panel, style="Card.TFrame")
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(
            text_frame,
            bg="#f7f9fb",
            fg="#344155",
            relief="flat",
            wrap="word",
            font=("Microsoft YaHei UI", 9),
            padx=10,
            pady=10,
            state="disabled",
            height=10,
        )
        scroll = ttk.Scrollbar(text_frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("WARNING", foreground="#a2600e")
        self.text.tag_configure("ERROR", foreground="#b52f38")
        self.text.tag_configure("DEBUG", foreground="#677b91")
        ttk.Label(panel, textvariable=self.issue, wraplength=750, style="Hint.TLabel").pack(
            anchor="w", pady=(8, 0)
        )
        ttk.Label(
            outer,
            text="界面保留最近 1500 条；完整日志保存在程序目录，按大小轮转。",
            background="#eef2f6",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(10, 0))

    def start(self):
        if self.closing or self.controller.running:
            return
        try:
            if not self.preview:
                self.snapshot = self.services.save_settings(
                    {
                        "backpack": {"auto_clear_enabled": str(self.auto_clear.get()).lower()},
                        "diagnostics": {
                            "qte_detail_log": str(self.detail_log.get()).lower(),
                            "qte_feedback_enabled": str(self.feedback.get()).lower(),
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
        except Exception as exc:
            log.exception("无法开始任务")
            self.controller.last_error = str(exc)

    def _run(self):
        self.target(self.snapshot, location=self.selected_location, interactive=False)

    def stop(self):
        self.controller.stop()

    def close(self):
        self.closing = True
        self.stop()

    def _poll(self):
        pending = []
        for _ in range(200):
            try:
                level, text = self.handler.messages.get_nowait()
            except queue.Empty:
                break
            self.records.append((level, text))
            pending.append((level, text))
            if level >= logging.WARNING:
                self.issue.set("最近提示：" + text.splitlines()[0][-170:])
        if pending:
            self._append(pending)
        active = self.controller.running
        state = "disabled" if active or self.closing else "normal"
        self.start_button.configure(state=state)
        self.stop_button.configure(state="normal" if active and not self.closing else "disabled")
        for widget in (self.clear_check, self.awake_check, self.trace_check, self.feedback_check):
            widget.configure(state=state)
        self.location_box.configure(state="disabled" if active or self.closing else "readonly")
        if self.closing:
            self.status.set("正在关闭")
            self.detail.set("等待当前操作退出并释放按键、截图和电源请求…")
            if not active:
                logging.getLogger().removeHandler(self.handler)
                self.root.destroy()
                return
        elif active:
            stopping = self.controller.control.stopped.is_set()
            self.status.set("正在停止" if stopping else self.controller.control.phase)
            self.detail.set("点击停止任务结束运行；切离游戏、锁屏或移动窗口也会停止任务。")
        else:
            self.status.set("需要处理" if self.controller.last_error else "待机")
            self.detail.set(
                self.controller.last_error
                or self.controller.last_stop_reason
                or "点击开始，自动聚焦游戏后运行。"
            )
        self.root.after(80, self._poll)

    def _render(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self._append(self.records)

    def _append(self, records):
        minimum = {
            "运行信息": logging.INFO,
            "警告 / 错误": logging.WARNING,
            "详细诊断": logging.DEBUG,
        }[self.level.get()]
        position = self.text.yview()[0]
        self.text.configure(state="normal")
        for level, message in records:
            if level >= minimum:
                tag = (
                    "ERROR"
                    if level >= logging.ERROR
                    else "WARNING"
                    if level >= logging.WARNING
                    else "DEBUG"
                    if level < logging.INFO
                    else "INFO"
                )
                self.text.insert("end", message[:5000] + "\n", tag)
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > 2000:
            self.text.delete("1.0", f"{lines - 2000}.0")
        if self.handler.skipped:
            self.issue.set(f"界面繁忙，已跳过 {self.handler.skipped} 条展示副本；请查看文件日志。")
        self.text.configure(state="disabled")
        if self.follow.get():
            self.text.see("end")
        else:
            self.text.yview_moveto(position)

    def open_logs(self):
        os.startfile(str(self.config_path.parent))

    def _callback_error(self, exc_type, exc, tb):
        log.error("界面操作异常", exc_info=(exc_type, exc, tb))
        self.controller.last_error = str(exc)


def launch(target, *, preview=False):
    if preview:

        def target(*args, **kwargs):
            run_control.set_status("模拟任务运行中")
            log.info("模拟任务开始：不连接游戏")
            run_control.sleep(180)

    root = tk.Tk()
    try:
        FishingApp(root, target, preview=preview)
    except Exception as exc:
        log.exception("程序页面初始化失败")
        messagebox.showerror(
            "无法打开程序", f"{exc}\n\n详细信息已写入程序目录的 auto_fishing.log", parent=root
        )
        root.destroy()
        return
    root.mainloop()
