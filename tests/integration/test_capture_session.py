"""模拟 DXcam 旧工厂列表与新显示器布局不一致，验证截图会话不依赖旧索引。"""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bd2_fishing.infrastructure.windows import capture as capture_backend
from bd2_fishing.infrastructure.windows import display as displays
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime import geometry as geometry


class CaptureSessionTests(unittest.TestCase):
    def output(self, name, bounds):
        return SimpleNamespace(
            attached_to_desktop=True,
            devicename=name,
            update_desc=Mock(),
            desc=SimpleNamespace(
                DesktopCoordinates=SimpleNamespace(
                    left=bounds[0], top=bounds[1], right=bounds[2], bottom=bounds[3]
                )
            ),
        )

    def modules(self, adapters, constructor, legacy):
        return {
            "dxcam": SimpleNamespace(DXCamera=constructor, create=legacy),
            "dxcam.core.device": SimpleNamespace(Device=lambda adapter: adapter),
            "dxcam.core.output": SimpleNamespace(Output=lambda pointer: pointer),
            "dxcam.util.io": SimpleNamespace(
                enum_dxgi_adapters=adapters, enum_dxgi_outputs=lambda adapter: adapter
            ),
        }

    def test_new_right_output_ignores_short_cached_factory_and_reenumerates_on_restart(self):
        primary = self.output("primary", (0, 0, 1920, 1080))
        right = self.output("right", (1920, 0, 3840, 1080))
        old_adapter, new_adapter = [primary, right], [right]
        adapters = Mock(side_effect=[[old_adapter], [[], new_adapter]])
        legacy = Mock(side_effect=IndexError("list index out of range"))
        cameras = [Mock(), Mock()]
        constructor = Mock(side_effect=cameras)
        region = geometry.Rect(1936, 577, 2811, 1069)
        with (
            patch.dict(sys.modules, self.modules(adapters, constructor, legacy)),
            patch.object(run_control, "sleep"),
        ):
            for output_index in (1, 0):
                with capture_backend.DxCameraCapture(window_region=region) as capture:
                    self.assertEqual(capture._monitor.output_idx, output_index)
                    capture.grab(region)
        self.assertEqual(adapters.call_count, 2)
        legacy.assert_not_called()
        self.assertIs(constructor.call_args_list[0].kwargs["device"], old_adapter)
        self.assertIs(constructor.call_args_list[1].kwargs["device"], new_adapter)
        for call, camera in zip(constructor.call_args_list, cameras):
            self.assertIs(call.kwargs["output"], right)
            self.assertEqual(call.kwargs["output_color"], "BGR")
            camera.grab.assert_called_once_with(region=(16, 577, 891, 1069))
            camera.release.assert_called_once()

    def test_cancel_after_creation_releases_unreturned_camera(self):
        output = self.output("primary", (0, 0, 1920, 1080))
        camera = Mock()
        with (
            patch.dict(
                sys.modules, self.modules(lambda: [[output]], Mock(return_value=camera), Mock())
            ),
            patch.object(run_control, "sleep", side_effect=run_control.RunStopped()),
            self.assertRaises(run_control.RunStopped),
        ):
            displays.create_camera_for_region((10, 10, 110, 110))
        camera.release.assert_called_once()

    def test_layout_changes_during_creation_do_not_use_stale_coordinates(self):
        output = self.output("primary", (0, 0, 1920, 1080))
        output.update_desc.side_effect = lambda: setattr(
            output.desc.DesktopCoordinates, "left", 1920
        )
        constructor = Mock()
        with (
            patch.dict(sys.modules, self.modules(lambda: [[output]], constructor, Mock())),
            self.assertRaisesRegex(RuntimeError, "布局在截图初始化期间变化"),
        ):
            displays.create_camera_for_region((10, 10, 110, 110))
        constructor.assert_not_called()

    def test_missing_output_has_actionable_error_without_creating_camera(self):
        constructor = Mock()
        with (
            patch.dict(sys.modules, self.modules(lambda: [], constructor, Mock())),
            self.assertRaisesRegex(RuntimeError, "没有可用显示器"),
        ):
            displays.create_camera_for_region((10, 10, 110, 110))
        constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
