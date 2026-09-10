"""实际 Tk 窗口集成检查，按钮驱动模拟任务，不发送任何游戏输入。"""

import argparse
import logging
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import win32gui

from bd2_fishing.app.desktop import DesktopServices
from bd2_fishing.infrastructure.windows import window as window
from bd2_fishing.runtime import control as run_control
from bd2_fishing.ui.window import FishingApp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hidden", action="store_true", help="隐藏窗口，仅验证交互逻辑，不抢占游戏焦点"
    )
    parser.add_argument(
        "--short-screen", action="store_true", help="模拟 125%% 缩放与 1366×768 短屏幕布局"
    )
    args = parser.parse_args()
    hidden = args.hidden
    if hidden and args.short_screen:
        parser.error("--short-screen 需要显示测试窗口，不能与 --hidden 同用")
    window.enable_dpi_awareness()
    logging.basicConfig(level=logging.INFO)
    calls = []

    def task(*args, **kwargs):
        calls.append(args[0].getboolean("diagnostics", "qte_detail_log"))
        run_control.set_status("模拟任务运行中")
        run_control.sleep(60)

    root = tk.Tk()
    if args.short_screen:
        root.tk.call("tk", "scaling", 120 / 72)
    if hidden:
        root.withdraw()
    temporary = tempfile.TemporaryDirectory()
    services = DesktopServices(config_path=Path(temporary.name) / "config.ini")
    work_area = (0, 0, 1366, 728)
    if args.short_screen:
        with patch(
            "bd2_fishing.infrastructure.windows.desktop_placement.win32api.GetMonitorInfo",
            return_value={"Work": work_area},
        ):
            app = FishingApp(root, task, preview=True, services=services)
            root.update()
    else:
        app = FishingApp(root, task, preview=True, services=services)
    callback_errors = []
    root.report_callback_exception = lambda *args: callback_errors.append(args)
    if not args.short_screen:
        root.geometry("1040x720")
    root.update_idletasks()
    # 仍使用模拟任务与空输入释放回调，设置服务只访问临时配置。
    app.preview = False
    app.preferences.preview = False

    def pump(predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            assert not callback_errors, callback_errors
            if predicate():
                return
            time.sleep(0.02)
        raise AssertionError("UI did not reach expected state")

    try:
        root.update_idletasks()
        if args.short_screen:
            bounds = win32gui.GetWindowRect(win32gui.GetAncestor(root.winfo_id(), 2))
            assert bounds[0] >= work_area[0] and bounds[1] >= work_area[1], bounds
            assert bounds[2] <= work_area[2] and bounds[3] <= work_area[3], bounds
            app.open_preferences()
            root.update_idletasks()
            for widget in (app.action_button, app.preferences.save_button):
                assert widget.winfo_viewable()
                assert widget.winfo_rooty() + widget.winfo_height() <= work_area[3]
            app.open_run()
        assert not app.controller.running
        app.preferences_button.invoke()
        dialog = app.preferences
        # 保持真实父子窗口关系，同时验证居中后的实际布局。
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
        assert dialog.suggestions["expected_window_width"].get() == "实测 945 px"
        assert dialog.suggestions["expected_window_height"].get() == "实测 532 px"
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
        assert dialog.suggestions["loop_sleep_seconds"].get() == "本机建议 5 ms"
        assert dialog.suggestions["feedback_poll_seconds"].get() == "本机建议 10 ms"
        assert "需实测" in dialog.suggestions["qte_hold_seconds"].get()
        assert services.load_settings().getfloat("time", "loop_sleep_seconds") == 0.02
        dialog.toggle_advanced()
        if not hidden:
            pump(lambda: dialog.calibrate_button.master.winfo_height() > 1)
            for key, entry in dialog.entries.items():
                label = dialog.suggestion_labels[key]
                assert label.winfo_x() >= entry.winfo_x() + entry.winfo_width()
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
        assert not dialog.dirty
        dialog.values["qte_hold_seconds"].set("90")
        app.open_run()
        app.start()
        assert not app.controller.running
        assert app.settings_visible
        assert dialog.dirty
        dialog.discard()
        assert dialog.values["qte_hold_seconds"].get() == "80"
        assert not dialog.dirty
        assert not hasattr(app, "tabs")
        assert not hasattr(app, "header_stop")
        action_widget = app.action_button
        for cycle in (1, 2):
            app.detail_log.set(cycle == 2)
            dialog.save()
            app.open_run()
            # 检测任务完成后，主界面在下一次轮询才恢复按钮；不依赖线程完成的时机。
            pump(lambda: not app.action_button.instate(["disabled"]))
            app.action_button.invoke()
            pump(lambda: app.status.get() == "模拟任务运行中")
            assert app.action_button is action_widget
            assert "停止任务" in app.action_button.cget("text")
            assert not app.action_button.instate(["disabled"])
            assert app.snapshot.getboolean("diagnostics", "qte_detail_log") == (cycle == 2)
            assert app.snapshot.getfloat("time", "qte_hold_seconds") == 0.08
            assert not app.preferences_button.instate(["disabled"])
            app.open_preferences()
            assert dialog.entries["qte_hold_seconds"].instate(["disabled"])
            assert dialog.save_button.instate(["disabled"])
            assert not app.action_button.instate(["disabled"])
            app.start()
            assert len(calls) == cycle
            app.action_button.invoke()
            pump(lambda: app.status.get() == "待机")
            assert not app.controller.running
        assert calls == [False, True]
        assert app.action_button is action_widget
        assert "开始钓鱼" in app.action_button.cget("text")
        initial = app.auto_clear.get()
        app.clear_check.invoke()
        assert app.auto_clear.get() != initial
        app.clear_check.invoke()
        assert app.auto_clear.get() == initial
        assert "Tick.indicator" in str(tk.ttk.Style(root).layout("TCheckbutton"))
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
        # 两个队列分批读取时，警告立即显示，剩余的旧诊断必须回到警告之前。
        for same_time in (False, True):
            prefix = f"backlog-{same_time}"
            stamp = time.time()
            for index in range(120):
                record = logging.LogRecord(
                    "smoke_backlog", logging.DEBUG, __file__, 1, f"{prefix}-{index:03d}", (), None
                )
                record.created = stamp if same_time else stamp + index / 1000
                app.handler.handle(record)
            warning = logging.LogRecord(
                "smoke_backlog", logging.WARNING, __file__, 1, f"{prefix}-warning", (), None
            )
            warning.created = stamp if same_time else stamp + 0.12
            app.handler.handle(warning)

            def poll_once():
                root.after_cancel(app._poll_id)
                app._poll()

            poll_once()
            shown = app.text.get("1.0", "end")
            assert f"{prefix}-warning" in shown
            assert f"{prefix}-119" not in shown
            poll_once()
            shown = app.text.get("1.0", "end")
            positions = [shown.index(f"{prefix}-{index:03d}") for index in range(120)]
            positions.append(shown.index(f"{prefix}-warning"))
            assert positions == sorted(positions), positions
        app.level.set("警告 / 错误")
        app._render()
        assert "smoke informational entry" not in app.text.get("1.0", "end")
        assert "smoke warning entry" in app.text.get("1.0", "end")
        # 最小支持尺寸下，按钮与设置控件仍留在各自容器内。
        app.open_run()
        root.geometry("960x640")
        root.update_idletasks()
        for widget in (
            ()
            if hidden
            else (
                app.action_button,
                app.location_box,
                app.clear_check,
                app.awake_check,
                app.preferences_button,
            )
        ):
            assert widget.winfo_x() + widget.winfo_width() <= widget.master.winfo_width(), (
                widget.cget("text") if "text" in widget.keys() else str(widget),
                widget.winfo_x(),
                widget.winfo_width(),
                widget.master.winfo_width(),
            )
        # 草稿退出可取消；再次退出后由轮询正常销毁主窗口。
        dialog.values["qte_hold_seconds"].set("90")
        with patch("bd2_fishing.ui.window.messagebox.askyesno", return_value=False):
            app.close()
        assert not app.closing
        dialog.discard()
        assert not callback_errors, callback_errors
        if hidden:
            assert root.state() == "withdrawn"
            print("Hidden mode: no mapped windows, no game access; visual layout checks skipped")
        if args.short_screen:
            print("PASS: 125% scaling, short-screen window bounds and start/save button visibility")
        print(
            "PASS: fixed task controls and one start/stop button, settings draft/save/discard, detection/calibration advice, read-only settings and stop during two task cycles, log filters, close cancellation"
        )
    finally:
        if app._poll_id:
            root.after_cancel(app._poll_id)
        app.preferences.close()
        app.controller.close()
        logging.getLogger().removeHandler(app.handler)
        root.destroy()
        temporary.cleanup()


if __name__ == "__main__":
    main()
