import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import configparser

from app_ui import UILogHandler, update_config_options
import run_control
import session_support
import utils
import main as fishing
from ocr.ocr_enum import FishingLocation


class AppSessionTests(unittest.TestCase):
    def test_gui_manual_location_does_not_need_ocr_or_console(self):
        config = configparser.ConfigParser()
        config.read_string(utils.DEFAULT_CONFIG_CONTENT)
        bot = fishing.FishingBot(config, utils.Rect(0, 0, 1152, 648), Mock(),
                                 location=FishingLocation.ABYSS_MAW, interactive=False)
        with patch.object(fishing.ocr_service, "detect_location_from_ocr") as detect, \
                patch.object(run_control, "console_input") as prompt:
            strategy = bot.choose_strategy(Mock())
        self.assertEqual(type(strategy).__name__, "AbyssMawQTEStrategy")
        detect.assert_not_called()
        prompt.assert_not_called()

    def test_gui_ocr_failure_requests_page_selection_without_console_wait(self):
        config = configparser.ConfigParser()
        config.read_string(utils.DEFAULT_CONFIG_CONTENT)
        bot = fishing.FishingBot(config, utils.Rect(0, 0, 1152, 648), Mock(), interactive=False)
        with patch.object(fishing.ocr_service, "detect_location_from_ocr", return_value=None), \
                patch.object(run_control, "console_input") as prompt:
            with self.assertRaisesRegex(RuntimeError, "程序页面选择钓场"):
                bot.choose_strategy(Mock())
        prompt.assert_not_called()

    def test_foreground_guard_treats_focus_loss_as_user_stop(self):
        with patch.object(utils.win32gui, "FindWindow", return_value=1), \
                patch.object(session_support, "input_desktop_available", return_value=True), \
                patch.object(utils.win32gui, "GetForegroundWindow", return_value=2):
            guard = utils.WindowGuard("test", utils.Rect(0, 0, 100, 100), require_foreground=True)
            with self.assertRaisesRegex(run_control.RunStopped, "失去焦点"):
                guard()

    def test_ui_saves_only_owned_options_and_preserves_comments(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.ini"
            path.write_text("; user's settings\n[hook]\nhue = 35\n\n[backpack]\n; comment\nauto_clear_enabled = true\n", encoding="utf-8-sig")
            config = update_config_options(path, {"backpack": {"auto_clear_enabled": "false"}, "app": {"prevent_sleep": "true", "location": "深渊巨口"}})
            self.assertFalse(config.getboolean("backpack", "auto_clear_enabled"))
            self.assertEqual(config.getint("hook", "hue"), 35)
            self.assertTrue(config.getboolean("app", "prevent_sleep"))
            self.assertIn("; comment", path.read_text(encoding="utf-8-sig"))
            update_config_options(path, {"app": {"prevent_sleep": "false"}})
            self.assertEqual(path.read_text(encoding="utf-8-sig").count("[app]"), 1)

    def test_ui_queue_is_bounded_without_filtering_file_handler(self):
        ui = UILogHandler()
        logger = logging.Logger("test", logging.DEBUG)
        file_handler = Mock(spec=logging.Handler)
        file_handler.level = logging.DEBUG
        logger.addHandler(ui)
        logger.addHandler(file_handler)
        for i in range(2010):
            logger.info("entry %d", i)
        self.assertEqual(ui.messages.qsize(), 2000)
        self.assertEqual(ui.skipped, 10)
        self.assertEqual(file_handler.handle.call_count, 2010)

    def test_start_restores_minimized_game_and_verifies_foreground(self):
        with patch.object(session_support, "input_desktop_available", return_value=True), \
                patch.object(session_support.win32gui, "FindWindow", return_value=123), \
                patch.object(session_support.win32gui, "IsIconic", return_value=True), \
                patch.object(session_support.win32gui, "ShowWindow") as restore, \
                patch.object(session_support.win32gui, "SetForegroundWindow") as focus, \
                patch.object(session_support.win32gui, "GetForegroundWindow", return_value=123):
            self.assertEqual(session_support.focus_game("test"), 123)
        restore.assert_called_once_with(123, 9)
        focus.assert_called_once_with(123)

    def test_denied_focus_does_not_start_gameplay(self):
        with patch.object(session_support, "input_desktop_available", return_value=True), \
                patch.object(session_support.win32gui, "FindWindow", return_value=123), \
                patch.object(session_support.win32gui, "IsIconic", return_value=False), \
                patch.object(session_support.win32gui, "SetForegroundWindow", side_effect=OSError("denied")), \
                patch.object(session_support.win32gui, "GetForegroundWindow", return_value=456), \
                patch.object(run_control, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "未能自动聚焦"):
                session_support.focus_game("test")

    def test_locked_desktop_rejects_focus_attempt(self):
        with patch.object(session_support, "input_desktop_available", return_value=False), \
                patch.object(session_support.win32gui, "SetForegroundWindow") as focus:
            with self.assertRaisesRegex(RuntimeError, "解锁"):
                session_support.focus_game("test")
        focus.assert_not_called()

    def test_power_request_restores_previous_state_after_cancellation(self):
        setter = Mock(return_value=0x80000000)
        with patch.object(session_support.ctypes.windll.kernel32, "SetThreadExecutionState", setter):
            with self.assertRaises(run_control.RunStopped):
                with session_support.keep_awake(True):
                    raise run_control.RunStopped()
        self.assertEqual([call.args[0] for call in setter.call_args_list], [0x80000003, 0x80000000])

    def test_disabled_power_option_leaves_system_alone(self):
        with patch.object(session_support.ctypes.windll.kernel32, "SetThreadExecutionState") as setter:
            with session_support.keep_awake(False):
                pass
            setter.assert_not_called()

    def test_focus_loss_interrupts_guarded_wait(self):
        checks = Mock(side_effect=[None, RuntimeError("focus lost")])
        with run_control.use_control(run_control.RunControl()), run_control.use_input_guard(checks):
            with self.assertRaisesRegex(RuntimeError, "focus lost"):
                run_control.sleep(60)


if __name__ == "__main__":
    unittest.main()
