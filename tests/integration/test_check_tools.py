"""检查工具入口的回归，通过模拟窗口避免连接真实游戏。"""

import unittest
from unittest.mock import patch

from scripts.checks import smoke_feedback_capture


class CheckToolTests(unittest.TestCase):
    def test_missing_window_reports_expected_error_before_capture(self):
        with (
            patch.object(smoke_feedback_capture.window_backend, "enable_dpi_awareness") as dpi,
            patch.object(
                smoke_feedback_capture.window_backend, "get_window_region", return_value=None
            ),
            patch.object(smoke_feedback_capture.capture_backend, "DxCameraCapture") as capture,
        ):
            with self.assertRaisesRegex(RuntimeError, "未找到游戏窗口"):
                smoke_feedback_capture.main()
        dpi.assert_called_once_with()
        capture.assert_not_called()
