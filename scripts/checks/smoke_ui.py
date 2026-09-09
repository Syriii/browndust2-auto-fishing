"""实际 Tk 窗口集成检查，按钮驱动模拟任务，不发送任何游戏输入。"""

import logging
import tempfile
import time
import tkinter as tk
from pathlib import Path

from bd2_fishing.app.desktop import DesktopServices
from bd2_fishing.infrastructure.windows import window as window
from bd2_fishing.runtime import control as run_control
from bd2_fishing.ui.window import FishingApp


def main():
    window.enable_dpi_awareness()
    logging.basicConfig(level=logging.INFO)
    calls = []

    def task(*args, **kwargs):
        calls.append(args[0].getboolean("diagnostics", "qte_detail_log"))
        run_control.set_status("模拟任务运行中")
        run_control.sleep(60)

    root = tk.Tk()
    temporary = tempfile.TemporaryDirectory()
    services = DesktopServices(config_path=Path(temporary.name) / "config.ini")
    app = FishingApp(root, task, preview=True, services=services)
    root.geometry("760x640")
    root.update_idletasks()
    root.withdraw()
    # 仍使用模拟任务与空输入释放回调，设置服务只访问临时配置。
    app.preview = False

    def pump(predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            if predicate():
                return
            time.sleep(0.02)
        raise AssertionError("UI did not reach expected state")

    try:
        root.update_idletasks()
        assert not app.controller.running
        app.preferences_button.invoke()
        dialog = app.preferences
        # 主窗口隐藏时，解除 transient 才能实际布局独立设置页。
        dialog.window.transient("")
        dialog.window.deiconify()
        dialog.window.update_idletasks()
        services.inspect_device = lambda: dict(
            width=945,
            height=532,
            position=(0, 0),
            display="模拟显示器",
            display_bounds=(0, 0, 1920, 1080),
            dpi=96,
            scale_percent=100,
            wait_precision=[dict(requested_ms=10, median_ms=11, max_ms=12)],
        )
        dialog.detect_button.invoke()
        pump(lambda: dialog.device is not None)
        dialog.use_button.invoke()
        assert dialog.values["expected_window_width"].get() == "945"
        services.calibrate_timing = lambda cancel: dict(
            recommendation={"loop_sleep_seconds": "5", "feedback_poll_seconds": "10"},
            reason="模拟时钟校准",
            limitation="只验证页面，不操作游戏",
        )
        dialog.calibrate_button.invoke()
        pump(lambda: dialog.calibration is not None)
        dialog.apply_calibration_button.invoke()
        assert dialog.values["loop_sleep_seconds"].get() == "5"
        assert dialog.values["qte_hold_seconds"].get() == "100"
        assert services.load_settings().getfloat("time", "loop_sleep_seconds") == 0.02
        dialog.calibrate_button.master.master.select(dialog.calibrate_button.master)
        dialog.window.update_idletasks()
        for widget in (dialog.calibrate_button, dialog.apply_calibration_button):
            assert widget.winfo_y() + widget.winfo_height() <= widget.master.winfo_height(), (
                widget.winfo_y(),
                widget.winfo_height(),
                widget.master.winfo_height(),
            )
        dialog.values["loop_sleep_seconds"].set("10")
        dialog.values["qte_hold_seconds"].set("80")
        dialog.save()
        assert services.load_settings().getfloat("time", "qte_hold_seconds") == 0.08
        for cycle in (1, 2):
            app.detail_log.set(cycle == 2)
            app.start_button.invoke()
            pump(lambda: app.status.get() == "模拟任务运行中")
            assert app.start_button.instate(["disabled"])
            assert not app.stop_button.instate(["disabled"])
            assert app.snapshot.getboolean("diagnostics", "qte_detail_log") == (cycle == 2)
            assert app.snapshot.getfloat("time", "qte_hold_seconds") == 0.08
            assert app.preferences_button.instate(["disabled"])
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
        for widget in (
            app.start_button,
            app.stop_button,
            app.location_box,
            app.clear_check,
            app.awake_check,
            app.trace_check,
            app.preferences_button,
        ):
            assert widget.winfo_x() + widget.winfo_width() <= widget.master.winfo_width(), (
                widget.cget("text") if "text" in widget.keys() else str(widget),
                widget.winfo_x(),
                widget.winfo_width(),
                widget.master.winfo_width(),
            )
        print(
            "PASS: idle, two start/stop cycles, detail log setting saved/applied, log filtering and minimum-size layout"
        )
    finally:
        app.controller.close()
        logging.getLogger().removeHandler(app.handler)
        root.destroy()
        temporary.cleanup()


if __name__ == "__main__":
    main()
