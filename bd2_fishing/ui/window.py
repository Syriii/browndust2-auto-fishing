"""ui.window：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging
import tkinter as tk
from collections import deque
from tkinter import messagebox

from PIL import ImageTk

from bd2_fishing.app.desktop import DesktopServices, FishingLocation
from bd2_fishing.runtime import control as run_control
from bd2_fishing.ui.logs import UILogHandler
from bd2_fishing.ui.updates import UpdatePanel
from bd2_fishing.ui.workspace import build_workspace

log = logging.getLogger(__name__)


class FishingApp:
    def __init__(self, root, target, *, preview=False, services=None):
        self.root, self.target, self.preview = root, target, preview
        self.services = services or DesktopServices(read_only=preview)
        self.collection = self.services.fishing_collection_service()
        self.task_mode = tk.StringVar(value="自由钓鱼")
        self._collection_revision = -1
        self._collection_active = False
        self._evidence_photos = {}
        self.current_page = "run"
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
        self.root.bind("<Destroy>", self._destroyed, add="+")
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
        build_workspace(self, locations)

    def _destroyed(self, event):
        if event.widget is self.root and not self.controller.running:
            self.collection.journal.close()

    def _resize_details(self, event):
        width = max(160, event.width - 36)
        if hasattr(self, "detail_label"):
            self.detail_label.configure(wraplength=width)
        self.issue_label.configure(wraplength=width)

    def save_targets(self, selected):
        if self.controller.running:
            return False
        try:
            self.collection.save_targets(selected)
        except Exception as exc:
            log.exception("目标保存失败")
            messagebox.showerror(
                "目标未保存", f"无法写入目标，请检查存储空间后重试。\n{exc}", parent=self.root
            )
            return False
        return True

    def collection_photo(self, item, size):
        key = item["id"], size
        if key not in self._evidence_photos:
            photo = self.collection.picture(item["id"], size)
            self._evidence_photos[key] = (
                ImageTk.PhotoImage(photo, master=self.root) if photo else None
            )
        return self._evidence_photos[key]

    def show_page(self, page):
        if self.closing:
            return
        visible = "catalogue" if page == "target-picker" else page
        for key, widget in self.pages.items():
            if key == visible:
                widget.grid(row=0, column=0, sticky="nsew")
            else:
                widget.grid_remove()
        self.current_page = page
        self.settings_visible = page == "settings"
        for key, button in self.nav_buttons.items():
            button.state(
                ["pressed"]
                if key == ("targets" if page == "target-picker" else page)
                else ["!pressed"]
            )
        if page == "targets":
            self.targets_page.render()
        elif page == "catches":
            self.catches_page.render()
        elif page in ("catalogue", "target-picker"):
            self.catalogue.after_idle(self.catalogue.render)

    def toggle_logs(self):
        if self.log_panel.winfo_manager():
            self.log_panel.pack_forget()
            self.log_toggle.configure(text="展开运行日志")
        else:
            self.log_panel.pack(fill="both", expand=True)
            self.log_toggle.configure(text="收起运行日志")

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
        if self.catalogue.picking:
            self.detail.set("请先保存或取消正在选择的目标，再开始任务。")
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
            self.catalogue.close()
            self.collection.begin(self.task_mode.get() == "按目标钓鱼")
            self.show_page("run")
            self.controller.start()
            self.preferences.set_locked(self.controller.running)
        except Exception as exc:
            log.exception("无法开始任务")
            self.controller.last_error = str(exc)

    def _run(self):
        self.target(
            self.snapshot,
            location=self.selected_location,
            interactive=False,
            collection=self.collection,
        )

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
        self.catalogue.close()
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
        self.catalogue_button.configure(state="disabled" if active or self.closing else "normal")
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
        self.mode_box.configure(state="disabled" if active or self.closing else "readonly")
        revision = self.collection.journal.revision
        if revision != self._collection_revision or active != self._collection_active:
            self._collection_revision, self._collection_active = revision, active
            count = len(self.collection.journal.targets())
            self.target_summary.configure(text=f"待完成 {count} 项目标要求 · 在目标页选择鱼与尺寸")
            if self.current_page == "targets":
                self.targets_page.render()
            elif self.current_page == "catches":
                self.catches_page.render()
        return self._refresh_status(active)

    def _refresh_status(self, active):
        if self.closing:
            self.status.set("正在关闭")
            self.detail.set("等待当前操作退出并释放按键、截图和电源请求…")
            if not active:
                logging.getLogger().removeHandler(self.handler)
                self.collection.journal.close()
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
        self.show_page("settings")

    def open_run(self):
        self.show_page("run")

    def toggle_preferences(self):
        if self.settings_visible:
            self.open_run()
        else:
            self.open_preferences()

    def _callback_error(self, exc_type, exc, tb):
        log.error("界面操作异常", exc_info=(exc_type, exc, tb))
        self.controller.last_error = str(exc)


def launch(target, *, preview=False, services=None, show_catalogue=False):
    if preview:

        def target(*args, **kwargs):
            run_control.set_status("模拟任务运行中")
            log.info("模拟任务开始：不连接游戏")
            run_control.sleep(180)

    root = tk.Tk()
    try:
        app = FishingApp(root, target, preview=preview, services=services)
        if preview and show_catalogue:
            app.catalogue.open()
    except Exception as exc:
        log.exception("程序页面初始化失败")
        messagebox.showerror(
            "无法打开程序", f"{exc}\n\n详细信息见运行目录的 logs/auto_fishing.log", parent=root
        )
        root.destroy()
        return
    root.mainloop()
