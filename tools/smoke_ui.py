"""实际 Tk 窗口集成检查，按钮驱动模拟任务，不发送任何游戏输入。"""

import logging
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app_ui import FishingApp
import run_control
import utils


def main():
    utils.enable_dpi_awareness()
    logging.basicConfig(level=logging.INFO)
    calls = []

    def task(*args, **kwargs):
        calls.append(args[0].getboolean("diagnostics", "qte_feedback_enabled"))
        run_control.set_status("模拟任务运行中")
        run_control.sleep(60)

    root = tk.Tk()
    app = FishingApp(root, task, preview=True)
    root.geometry("760x640")
    root.update_idletasks()
    root.withdraw()
    temporary = tempfile.TemporaryDirectory()
    # 仍使用模拟任务与空输入释放回调，仅将设置写入隔离的临时配置。
    app.config_path = Path(temporary.name) / "config.ini"
    app.preview = False

    def pump(predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            if predicate():
                return
            time.sleep(.02)
        raise AssertionError("UI did not reach expected state")

    try:
        root.update_idletasks()
        assert not app.controller.running
        for cycle in (1, 2):
            app.feedback.set(cycle == 2)
            app.start_button.invoke()
            pump(lambda: app.status.get() == "模拟任务运行中")
            assert app.start_button.instate(["disabled"])
            assert not app.stop_button.instate(["disabled"])
            assert app.feedback_check.instate(["disabled"])
            assert app.snapshot.getboolean("diagnostics", "qte_feedback_enabled") == (cycle == 2)
            app.stop_button.invoke()
            pump(lambda: app.status.get() == "待机")
            assert not app.controller.running
        assert calls == [False, True]
        logging.info("smoke informational entry")
        logging.warning("smoke warning entry")
        detail_logger = logging.getLogger("smoke_ui_detail")
        detail_logger.setLevel(logging.DEBUG)
        detail_logger.debug("smoke diagnostic detail")
        pump(lambda: "smoke warning entry" in app.text.get("1.0", "end"))
        assert "smoke diagnostic detail" not in app.text.get("1.0", "end")
        app.level.set("详细诊断")
        app._render()
        assert "smoke diagnostic detail" in app.text.get("1.0", "end")
        app.level.set("警告 / 错误")
        app._render()
        assert "smoke informational entry" not in app.text.get("1.0", "end")
        assert "smoke warning entry" in app.text.get("1.0", "end")
        # 最小支持尺寸下，按钮与设置控件仍留在各自容器内。
        root.geometry("760x640")
        root.update_idletasks()
        for widget in (app.start_button, app.stop_button, app.location_box, app.clear_check, app.awake_check, app.trace_check, app.feedback_check):
            assert widget.winfo_x() + widget.winfo_width() <= widget.master.winfo_width(), (
                widget.cget("text") if "text" in widget.keys() else str(widget),
                widget.winfo_x(), widget.winfo_width(), widget.master.winfo_width())
        print("PASS: idle, two start/stop cycles, feedback setting saved/applied, log filtering and minimum-size layout")
    finally:
        app.controller.close()
        logging.getLogger().removeHandler(app.handler)
        root.destroy()
        temporary.cleanup()


if __name__ == "__main__":
    main()
