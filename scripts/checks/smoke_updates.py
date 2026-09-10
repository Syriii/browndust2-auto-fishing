"""隐藏 Tk 更新页面检查；临时配置、模拟网络，不操作游戏或启动更新进程。"""

import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from bd2_fishing.app.desktop import DesktopServices
from bd2_fishing.ui.window import FishingApp


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        root.withdraw()
        app = FishingApp(
            root,
            lambda *a, **kw: None,
            preview=True,
            services=DesktopServices(config_path=Path(directory) / "config.ini"),
        )
        errors = []
        destroyed = []
        root.bind(
            "<Destroy>", lambda event: destroyed.append(True) if event.widget is root else None
        )
        root.report_callback_exception = lambda *args: errors.append(args)

        def pump(condition):
            deadline = time.monotonic() + 4
            while not condition():
                root.update()
                assert not errors, errors
                if time.monotonic() > deadline:
                    raise AssertionError("更新页面未完成预期状态")
                time.sleep(0.02)

        try:
            with patch(
                "bd2_fishing.ui.updates.center_window", side_effect=lambda w, *a: w.withdraw()
            ):
                app.updates.open()
            assert app.updates.window is not None
            gate = threading.Event()
            app.updates.job(lambda: gate.wait(2), lambda _: None)
            app.start()
            assert not app.controller.running
            gate.set()
            pump(lambda: not app.updates.busy)
            with patch.object(app.updates.service, "check", return_value={"version": "0.3.0"}):
                app.updates.check()
                pump(lambda: not app.updates.busy)
                assert app.updates.release["version"] == "0.3.0"
            with patch.object(app.updates.service, "check", side_effect=OSError("模拟网络失败")):
                app.updates.check()
                pump(lambda: not app.updates.busy)
                assert "从本地 ZIP 更新" in app.updates.notice.get()
            app.preview = False
            app.updates.storage["retention_days"].set("45")
            app.updates.save()
            assert app.services.load_settings().getint("storage", "retention_days") == 45
            app.updates.dismiss()
            app.close()
            pump(lambda: bool(destroyed))
        finally:
            if not destroyed:
                app.updates.close()
                root.destroy()
    print(
        "PASS: hidden update/storage window, busy start guard, network fallback, setting persistence"
    )


if __name__ == "__main__":
    main()
