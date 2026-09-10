"""更新及存储入口；后台操作通过队列回主线程，待机时才维护。"""

import logging
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from bd2_fishing.app.updates import RELEASES_URL
from bd2_fishing.ui.theme import center_window

log = logging.getLogger(__name__)


class UpdatePanel:
    def __init__(self, app):
        self.app = app
        self.service = app.services.update_service()
        self.busy = False
        self.cancel = threading.Event()
        self.results = queue.Queue(maxsize=1)
        self.window = None
        self.release = None
        self.notice = tk.StringVar(value=self.service.last_result())
        self._poll_id = None
        self._timer = app.root.after(500, self.startup)

    def startup(self):
        self._timer = None
        if self.app.closing or self.app.preview or not self.service.supported:
            return
        if not self.app.controller.running and not self.app.preferences.busy and not self.busy:
            check = self.app.services.load_settings().getboolean(
                "updates", "check_on_start", fallback=True
            )
            self.job(lambda: self._maintain(check), self._startup_result)
        self._timer = self.app.root.after(3600000, self.hourly)

    def hourly(self):
        self._timer = None
        if self.app.closing:
            return
        if not self.app.controller.running and not self.app.preferences.busy and not self.busy:
            self.job(lambda: self._maintain(False), self._startup_result)
        self._timer = self.app.root.after(3600000, self.hourly)

    def _maintain(self, check):
        removed = self.app.services.maintain_storage()
        if removed:
            log.info("已清理 %s 个过期日志或截图文件", removed)
        return self.service.check() if check else None

    def _startup_result(self, result):
        if isinstance(result, Exception):
            self.notice.set(f"更新检查或存储维护未完成：{result}。可打开 Release 页面手动下载。")
            log.warning(self.notice.get())
        elif result:
            self.release = result
            self.notice.set(f"发现新版本 {result['version']}，可下载并重启更新。")
            self.app.update_button.configure(text="发现新版本 · 更新")
            log.info(self.notice.get())

    def open(self):
        if self.app.controller.running or self.app.preferences.busy:
            messagebox.showinfo(
                "更新与存储", "请先停止任务并等待设备检测完成。", parent=self.app.root
            )
            return
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
        self.window = window = tk.Toplevel(self.app.root)
        window.title("更新与存储")
        window.transient(self.app.root)
        window.grab_set()
        body = ttk.Frame(window, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"当前版本 {self.service.version}").pack(anchor="w")
        ttk.Label(body, textvariable=self.notice, wraplength=550).pack(fill="x", pady=12)
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="检查更新", command=self.check).pack(side="left")
        ttk.Button(buttons, text="下载并更新", command=self.download).pack(side="left", padx=8)
        ttk.Button(buttons, text="从本地 ZIP 更新", command=self.local).pack(side="left")
        ttk.Button(
            body, text="打开 GitHub Release 下载页面", command=lambda: webbrowser.open(RELEASES_URL)
        ).pack(anchor="w", pady=12)
        ttk.Label(
            body,
            text="请选择官方完整 ZIP，无需解压。更新保留设置、数据和截图。\n更新包准备好后会再次确认重启；不会在钓鱼时替换文件。",
            wraplength=550,
        ).pack(anchor="w")
        config = self.app.services.load_settings()
        self.check_on_start = tk.BooleanVar(
            value=config.getboolean("updates", "check_on_start", fallback=True)
        )
        ttk.Checkbutton(body, text="启动时检查更新", variable=self.check_on_start).pack(
            anchor="w", pady=12
        )
        storage = ttk.LabelFrame(body, text="历史记录保留", padding=10)
        storage.pack(fill="x")
        self.storage = {}
        for row, (key, label, default) in enumerate(
            (
                ("retention_days", "保留天数（1–3650）", 30),
                ("logs_max_mb", "日志容量上限（MiB，10–102400）", 100),
                ("screenshots_max_mb", "截图容量上限（MiB，10–102400）", 2048),
            )
        ):
            value = tk.StringVar(value=config.get("storage", key, fallback=str(default)))
            self.storage[key] = value
            ttk.Label(storage, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(storage, textvariable=value, width=10).grid(row=row, column=1, padx=10)
        ttk.Label(
            body,
            text="启动及每小时待机时清理；screenshots/keep 内的证据保留。\n配置与校准数据不参与自动清理。",
            wraplength=550,
        ).pack(anchor="w", pady=12)
        ttk.Button(body, text="保存更新与存储设置", command=self.save).pack(anchor="e")
        window.protocol("WM_DELETE_WINDOW", self.dismiss)
        center_window(window, self.app.services, self.app.root)

    def save(self):
        if self.busy or self.app.preview:
            return
        try:
            values = {key: int(value.get()) for key, value in self.storage.items()}
            if not 1 <= values["retention_days"] <= 3650 or any(
                not 10 <= values[key] <= 102400 for key in ("logs_max_mb", "screenshots_max_mb")
            ):
                raise ValueError("保留设置超出标注范围")
            self.app.services.save_settings(
                {
                    "storage": {k: str(v) for k, v in values.items()},
                    "updates": {"check_on_start": str(self.check_on_start.get()).lower()},
                }
            )
            self.notice.set("更新与存储设置已保存；下次待机维护时生效。")
        except Exception as exc:
            messagebox.showerror("无法保存", str(exc), parent=self.window)

    def job(self, action, callback):
        if self.busy or self.app.closing:
            return
        self.busy = True

        def work():
            try:
                result = action()
            except Exception as exc:
                result = exc
            self.results.put((callback, result))

        threading.Thread(target=work, name="desktop-maintenance", daemon=True).start()
        self._poll_id = self.app.root.after(100, self.poll)

    def poll(self):
        self._poll_id = None
        try:
            callback, result = self.results.get_nowait()
        except queue.Empty:
            self._poll_id = self.app.root.after(100, self.poll)
            return
        self.busy = False
        if not self.app.closing:
            callback(result)

    def check(self):
        if not self.busy:
            self.notice.set("正在检查 GitHub 正式 Release…")
            self.job(self.service.check, self.checked)

    def checked(self, result):
        if isinstance(result, Exception):
            self.failed(result)
        else:
            self.release = result
            self.notice.set(
                f"发现新版本 {result['version']}。" if result else "当前已是最新正式版本。"
            )

    def failed(self, exc):
        self.notice.set(
            f"更新未完成：{exc}\n可打开 Release 页面下载 ZIP，再选择“从本地 ZIP 更新”。"
        )
        log.warning("更新未完成：%s", exc)

    def local(self):
        if self.busy or self.app.preview:
            return
        path = filedialog.askopenfilename(
            parent=self.window, title="选择官方完整更新包", filetypes=[("ZIP 更新包", "*.zip")]
        )
        if path:
            self.notice.set("正在校验并准备更新包…")
            self.job(lambda: self.service.prepare(package=path, cancel=self.cancel), self.prepared)

    def download(self):
        if self.busy or self.app.preview:
            return
        if not self.release:
            self.notice.set("请先检查更新。")
            return
        self.notice.set("正在下载并校验，完成前不会更改程序文件…")
        self.job(
            lambda: self.service.prepare(release=self.release, cancel=self.cancel), self.prepared
        )

    def prepared(self, result):
        if isinstance(result, Exception):
            self.failed(result)
            return
        self.notice.set(f"版本 {result['version']} 已校验，可重启更新。")
        if not messagebox.askyesno(
            "重启更新",
            f"安装版本 {result['version']} 并重启？\n原设置与运行数据会保留。",
            parent=self.window,
        ):
            return
        if self.app.preferences.dirty:
            self.notice.set("请先保存或撤销设备设置草稿，再重新选择更新包。")
            return
        try:
            self.service.launch(result)
            self.dismiss()
            self.app.close()
        except Exception as exc:
            self.failed(exc)

    def dismiss(self):
        if self.busy:
            self.notice.set("更新包正在准备，请等待完成后关闭。")
            return
        if self.window:
            self.window.destroy()
            self.window = None

    def close(self):
        self.cancel.set()
        for timer in (self._poll_id, self._timer):
            if timer:
                self.app.root.after_cancel(timer)
