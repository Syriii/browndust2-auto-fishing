"""桌面页面使用的设置、地点选项与任务服务。"""

import configparser
import json
import os
import platform
import time
import uuid
from pathlib import Path

from bd2_fishing.app.preferences import FIELDS, form_values, validate_form
from bd2_fishing.app.service import TaskController
from bd2_fishing.game.islands.catalog import FishingLocation as FishingLocation
from bd2_fishing.infrastructure import paths, settings

PREFERENCE_FIELDS = FIELDS


class DesktopServices:
    """隔离页面与配置文件、输入释放实现；构造时不操作游戏。"""

    def __init__(self, *, config_path=None, release_inputs=None, read_only=False):
        self.config_path = Path(config_path or paths.get_config_path())
        self._release_inputs = release_inputs
        self.read_only = read_only

    def load_settings(self):
        if self.read_only:
            config = configparser.ConfigParser()
            config.read_string(settings.DEFAULT_CONFIG_CONTENT)
            config.read(self.config_path, encoding="utf-8-sig")
            return config
        return settings.read_ini(str(self.config_path))

    def update_service(self):
        from bd2_fishing.app.updates import UpdateService

        return UpdateService()

    def maintain_storage(self):
        from bd2_fishing.infrastructure.maintenance import cleanup

        return cleanup(paths.get_base_path(), self.load_settings())

    def center_desktop_window(self, handle, parent_handle=None):
        from bd2_fishing.infrastructure.windows.desktop_placement import center_window

        center_window(handle, parent_handle)

    def desktop_client_size_limit(self, handle, parent_handle=None):
        from bd2_fishing.infrastructure.windows.desktop_placement import client_size_limit

        return client_size_limit(handle, parent_handle)

    def save_settings(self, updates):
        return settings.update_config_options(self.config_path, updates)

    def preference_values(self, *, defaults=False):
        default_config = configparser.ConfigParser()
        default_config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        return form_values(default_config if defaults else self.load_settings(), default_config)

    def save_preferences(self, values, *, detail_log=None):
        updates = validate_form(values)
        if detail_log is not None:
            updates["diagnostics"] = {"qte_detail_log": str(detail_log).lower()}
        return self.save_settings(updates)

    def open_log_directory(self):
        os.startfile(paths.get_log_path())

    def open_screenshot_directory(self):
        os.startfile(paths.get_diagnostics_path())

    def inspect_device(self, *, measure_precision=True):
        from bd2_fishing.game.constants import GAME_TITLE
        from bd2_fishing.infrastructure.windows import display, window

        window.enable_dpi_awareness()
        region = window.get_window_region(GAME_TITLE)
        if region is None:
            raise RuntimeError("未找到游戏窗口，请先打开游戏")
        outputs = display.enumerate_outputs()
        selected = display.select_output(outputs, region.as_tuple())
        hwnd = window.win32gui.FindWindow(None, GAME_TITLE)
        dpi = window.ctypes.windll.user32.GetDpiForWindow(hwnd)
        wait_precision = []
        for requested_ms in (5, 10, 20) if measure_precision else ():
            samples = []
            for _ in range(8):
                started = time.perf_counter()
                time.sleep(requested_ms / 1000)
                samples.append((time.perf_counter() - started) * 1000)
            samples.sort()
            wait_precision.append(
                dict(
                    requested_ms=requested_ms,
                    median_ms=round((samples[3] + samples[4]) / 2, 2),
                    max_ms=round(samples[-1], 2),
                )
            )
        return dict(
            width=region.width,
            height=region.height,
            position=(region.left, region.top),
            display=selected.name,
            display_bounds=selected.bounds,
            dpi=dpi,
            scale_percent=round(dpi / 96 * 100) if dpi else None,
            wait_precision=wait_precision,
        )

    def calibrate_timing(self, cancel):
        from bd2_fishing.app.calibration import measure_waits

        if cancel.is_set():
            raise RuntimeError("校准已取消")
        report = measure_waits(cancel)
        if cancel.is_set():
            raise RuntimeError("校准已取消")
        # 窗口数据只作测量上下文；没有游戏也能完成基础等待校准。
        try:
            device = self.inspect_device(measure_precision=False)
            device_error = None
        except Exception as exc:
            device, device_error = None, f"{type(exc).__name__}: {exc}"
        snapshot = configparser.ConfigParser()
        snapshot.read_string(settings.DEFAULT_CONFIG_CONTENT)
        snapshot.read(self.config_path, encoding="utf-8-sig")
        report.update(
            device=device,
            device_error=device_error,
            platform=platform.platform(),
            machine=platform.machine(),
            settings_snapshot=form_values(snapshot, snapshot),
        )
        if cancel.is_set():
            raise RuntimeError("校准已取消")
        directory = self.config_path.parent / "calibration"
        if self.config_path == paths.get_config_path():
            directory = paths.get_data_path() / "calibration"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "latest.json"
        temporary = directory / f".{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        report["report_path"] = str(target)
        return report

    def create_task(self, target, *, preview=False):
        if preview:

            def release():
                return None
        elif self._release_inputs is not None:
            release = self._release_inputs
        else:
            from bd2_fishing.infrastructure.windows.input import release_inputs

            release = release_inputs
        return TaskController(target, release)
