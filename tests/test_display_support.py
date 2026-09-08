"""多屏坐标、相机选择和输入保护回归；所有原生截图和输入均替换。"""

import configparser
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

import controlled_input
import display_support as displays
import run_control
import utils


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.outputs = [
            displays.DisplayOutput(0, 0, "primary", (0, 0, 1920, 1080)),
            displays.DisplayOutput(0, 1, "left", (-2560, -200, 0, 1240)),
            displays.DisplayOutput(1, 0, "right", (1920, 0, 4480, 1440)),
        ]

    def test_select_and_translate_primary_left_right_and_rotated_display(self):
        self.outputs.append(displays.DisplayOutput(1, 1, "portrait", (0, -1920, 1080, 0)))
        for absolute, index, local in (
            ((100, 50, 1200, 700), 0, (100, 50, 1200, 700)),
            ((-2400, -100, -1300, 600), 1, (160, 100, 1260, 800)),
            ((2100, 50, 3200, 700), 2, (180, 50, 1280, 700)),
            ((0, -1800, 900, -600), 3, (0, 120, 900, 1320)),
        ):
            with self.subTest(absolute=absolute):
                output = displays.select_output(self.outputs, absolute)
                self.assertEqual(output, self.outputs[index])
                self.assertEqual(output.local_region(absolute), local)

    def test_reject_spanning_offscreen_and_empty_regions(self):
        for region in ((-100, 100, 100, 700), (4400, 0, 5000, 700), (10, 10, 10, 20)):
            with self.subTest(region=region), self.assertRaises(RuntimeError):
                displays.select_output(self.outputs, region)

    def test_camera_uses_matching_gpu_and_output_and_releases(self):
        for region, device, output, local in (
            (utils.Rect(-2400, -100, -1300, 600), 0, 1, (160, 100, 1260, 800)),
            (utils.Rect(2100, 50, 3200, 700), 1, 0, (180, 50, 1280, 700)),
        ):
            with self.subTest(region=region):
                frame = np.zeros((2, 3, 3), dtype=np.uint8)
                camera = Mock(grab=Mock(side_effect=[None, frame]))
                selected = displays.select_output(self.outputs, region.as_tuple())
                factory = Mock(return_value=(camera, selected))
                with patch.object(displays, "create_camera_for_region", factory):
                    with utils.DxCameraCapture(window_region=region) as capture:
                        self.assertIsNone(capture.grab(region))
                        self.assertIs(capture.grab(region), frame)
                    factory.assert_called_once_with(region.as_tuple(), "BGR")
                    camera.grab.assert_called_with(region=local)
                    camera.release.assert_called_once()

    def test_factory_indices_skip_empty_adapters_but_keep_offline_output_slots(self):
        def output(attached, name):
            return SimpleNamespace(attached_to_desktop=attached, devicename=name,
                                   desc=SimpleNamespace(DesktopCoordinates=SimpleNamespace(
                                       left=0, top=0, right=1920, bottom=1080)))
        adapters = [[], [output(False, "offline"), output(True, "a")], [output(True, "b")]]
        with patch.dict(sys.modules, {
            "dxcam.util.io": SimpleNamespace(enum_dxgi_adapters=lambda: adapters,
                                             enum_dxgi_outputs=lambda adapter: adapter),
            "dxcam.core.output": SimpleNamespace(Output=lambda pointer: pointer),
        }):
            result = displays.enumerate_outputs()
        self.assertEqual([(o.device_idx, o.output_idx, o.name) for o in result], [(0, 1, "a"), (1, 0, "b")])

    def test_virtual_mouse_mapping_roundtrips_negative_zero_and_edge_pixels(self):
        bounds = (-2560, -200, 4480, 1440)
        for x, y in ((-2560, -200), (-1300, 100), (0, 0), (2300, 900), (4479, 1439)):
            with self.subTest(point=(x, y)):
                nx, ny = displays.normalize_virtual_point(x, y, bounds)
                self.assertEqual((nx * 7040 // 65536 - 2560, ny * 1640 // 65536 - 200), (x, y))
        with self.assertRaises(ValueError):
            displays.normalize_virtual_point(4480, 0, bounds)

    def test_default_and_source_configs_enable_automatic_cleanup(self):
        from pathlib import Path
        config = configparser.ConfigParser()
        config.read_string(utils.DEFAULT_CONFIG_CONTENT)
        self.assertTrue(config.getboolean("backpack", "auto_clear_enabled"))
        config.read(Path(__file__).resolve().parents[1] / "config.ini", encoding="utf-8-sig")
        self.assertTrue(config.getboolean("backpack", "auto_clear_enabled"))


class MouseAndWindowTests(unittest.TestCase):
    def test_move_uses_virtual_desktop_flag_and_preserves_zero_coordinate(self):
        events = []
        def send(count, pointer, size):
            event = pointer.contents.ii.mi
            events.append((event.dx, event.dy, event.dwFlags))
            return 1
        with patch.object(controlled_input._input, "SendInput", side_effect=send), \
                patch.object(controlled_input._input, "failSafeCheck"), \
                patch.object(controlled_input._input, "position", return_value=(300, 400)), \
                patch.object(controlled_input.win32api, "GetSystemMetrics",
                             side_effect=lambda i: {76: -1920, 77: 0, 78: 3840, 79: 1080}[i]):
            controlled_input.moveTo(-100, 0, _pause=False)
        nx, ny, flags = events[0]
        self.assertEqual((nx * 3840 // 65536 - 1920, ny * 1080 // 65536), (-100, 0))
        self.assertEqual(flags, 0xC001)

    def test_click_coordinates_cannot_reenter_primary_screen_conversion(self):
        with patch.object(controlled_input, "moveTo") as move, \
                patch.object(controlled_input._input, "click") as click:
            controlled_input.click(-100, 0)
        move.assert_called_once_with(-100, 0, _pause=False)
        click.assert_called_once_with(None, None)

    def test_window_movement_prevents_next_input_but_cleanup_still_runs(self):
        region = utils.Rect(0, 0, 1000, 700)
        with patch.object(utils.win32gui, "FindWindow", return_value=1), \
                patch.object(utils.win32gui, "IsWindow", return_value=True), \
                patch.object(utils.win32gui, "IsIconic", return_value=False), \
                patch.object(utils, "_client_region", return_value=region) as current:
            guard = utils.WindowGuard("test", region)
            control = run_control.RunControl()
            action, release = Mock(), Mock()
            with run_control.use_control(control), run_control.use_input_guard(guard):
                current.return_value = utils.Rect(1920, 0, 2920, 700)
                with self.assertRaisesRegex(RuntimeError, "移动或缩放"):
                    run_control.call_input(action)
                control.stop(release)
            action.assert_not_called()
            release.assert_called_once()
        # 上下文退出后不能残留上轮窗口的检查。
        run_control.checkpoint()

    def test_minimized_window_rejects_session(self):
        with patch.object(utils.win32gui, "FindWindow", return_value=1), \
                patch.object(utils.win32gui, "IsWindow", return_value=True), \
                patch.object(utils.win32gui, "IsIconic", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "最小化"):
                utils.WindowGuard("test", utils.Rect(0, 0, 1000, 700))()


if __name__ == "__main__":
    unittest.main()
