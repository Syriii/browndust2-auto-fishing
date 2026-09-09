"""本机设置校验、旧配置兼容及可取消输入时序；不操作游戏。"""

import configparser
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from bd2_fishing.app.desktop import DesktopServices
from bd2_fishing.app.preferences import verify_window_size
from bd2_fishing.game.fishing.qte import FrostStraitQTEStrategy
from bd2_fishing.infrastructure import settings
from bd2_fishing.infrastructure.windows import display, window
from bd2_fishing.infrastructure.windows import input as inputs
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class PreferencesTests(unittest.TestCase):
    def test_device_detection_checks_monitor_and_measures_wait_without_input(self):
        clock = [0.0]

        def wait(seconds):
            clock[0] += seconds + 0.002

        with (
            patch.object(window, "enable_dpi_awareness"),
            patch.object(window, "get_window_region", return_value=Rect(0, 0, 945, 532)),
            patch.object(
                display,
                "enumerate_outputs",
                return_value=[display.DisplayOutput(0, 0, "display", (0, 0, 1920, 1080))],
            ),
            patch.object(window.win32gui, "FindWindow", return_value=1),
            patch.object(window.ctypes.windll.user32, "GetDpiForWindow", return_value=144),
            patch("bd2_fishing.app.desktop.time.perf_counter", side_effect=lambda: clock[0]),
            patch("bd2_fishing.app.desktop.time.sleep", side_effect=wait),
            patch.object(inputs, "press") as press,
        ):
            result = self.services.inspect_device()
        self.assertEqual(result["scale_percent"], 150)
        self.assertEqual(result["width"], 945)
        self.assertEqual(result["wait_precision"][0]["median_ms"], 7)
        press.assert_not_called()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.ini"
        self.services = DesktopServices(config_path=self.path)

    def test_save_units_and_preserve_unmanaged_fields_and_comments(self):
        self.path.write_text(
            settings.DEFAULT_CONFIG_CONTENT + "\n; personal comment\n", encoding="utf8"
        )
        values = self.services.preference_values()
        self.assertEqual(values["qte_hold_seconds"], "100")
        values["qte_hold_seconds"] = "60"
        values["loop_sleep_seconds"] = "10"
        config = self.services.save_preferences(values)
        self.assertEqual(config.getfloat("time", "qte_hold_seconds"), 0.06)
        self.assertEqual(config.getfloat("time", "loop_sleep_seconds"), 0.01)
        self.assertEqual(config.getint("roi", "qte_press_tolerance_pixels"), 0)
        self.assertIn("; personal comment", self.path.read_text(encoding="utf-8-sig"))
        strategy = FrostStraitQTEStrategy(config, Rect(0, 0, 945, 532))
        with patch.object(inputs, "press_qte", return_value=True) as press:
            strategy._press_qte()
        press.assert_called_once_with(0.06, 0.2)

    def test_invalid_values_never_write(self):
        values = self.services.preference_values()
        original = self.path.read_bytes()
        for key, value in (
            ("loop_sleep_seconds", "nan"),
            ("qte_hold_seconds", "0"),
            ("expected_window_width", "1152.5"),
            ("feedback_poll_seconds", "inf"),
        ):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.services.save_preferences(dict(values, **{key: value}))
                self.assertEqual(self.path.read_bytes(), original)

    def test_old_config_uses_defaults_without_overwriting_personal_waits(self):
        self.path.write_text("[time]\nloop_sleep_seconds=0.01\n", encoding="utf8")
        values = self.services.preference_values()
        self.assertEqual(values["loop_sleep_seconds"], "10")
        self.assertEqual(values["qte_settle_seconds"], "200")
        self.assertNotIn("qte_settle_seconds", self.path.read_text())

    def test_window_size_auto_and_verify(self):
        values = self.services.preference_values()
        config = self.services.save_preferences(values)
        region = Rect(-945, 0, 0, 532)
        verify_window_size(config, region)
        config.set("app", "window_size_mode", "verify")
        with self.assertRaisesRegex(ValueError, "945×532"):
            verify_window_size(config, region)
        config.set("app", "expected_window_width", "945")
        config.set("app", "expected_window_height", "532")
        verify_window_size(config, region)

    def test_custom_press_wait_order_and_stop_release(self):
        actions = []
        with (
            patch.object(
                inputs._input,
                "keyDown",
                side_effect=lambda *a, **kw: actions.append("down") or True,
            ),
            patch.object(
                inputs._input, "keyUp", side_effect=lambda *a, **kw: actions.append("up") or True
            ),
            patch.object(control, "sleep", side_effect=lambda seconds: actions.append(seconds)),
        ):
            self.assertTrue(inputs.press_qte(0.05, 0.1))
        self.assertEqual(actions, ["down", 0.05, "up", 0.1])
        with (
            patch.object(inputs._input, "keyDown", return_value=True),
            patch.object(inputs._input, "keyUp", return_value=True) as release,
            patch.object(control, "sleep", side_effect=control.RunStopped("stop")) as sleep,
        ):
            with self.assertRaises(control.RunStopped):
                inputs.press_qte(0.05, 0.1)
        release.assert_called_once_with("space", _pause=False)
        sleep.assert_called_once_with(0.05)

    def test_release_after_stop_is_serialized_and_never_starts_new_input(self):
        stopped = control.RunControl()
        stopped.stopped.set()
        entered = threading.Event()
        done = threading.Event()

        def release():
            with control.use_control(stopped):
                entered.set()
                control.call_release(done.set)

        with stopped.input_lock:
            worker = threading.Thread(target=release)
            worker.start()
            self.assertTrue(entered.wait(1))
            self.assertFalse(done.is_set())
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertTrue(done.is_set())

    def test_stop_before_press_prevents_down_and_runtime_rejects_bad_delay(self):
        stopped = control.RunControl()
        stopped.stopped.set()
        with (
            control.use_control(stopped),
            patch.object(inputs._input, "keyDown") as down,
            patch.object(inputs._input, "keyUp"),
        ):
            with self.assertRaises(control.RunStopped):
                inputs.press_qte(0.05, 0.1)
        down.assert_not_called()
        config = configparser.ConfigParser()
        config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        config.set("time", "qte_hold_seconds", "nan")
        with self.assertRaises(ValueError):
            FrostStraitQTEStrategy(config, Rect(0, 0, 945, 532))
