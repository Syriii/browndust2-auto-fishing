"""新进程验证桌面浏览不导入游戏识别，任务入口仍转发参数和返回值。"""

import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bd2_fishing import bootstrap


class DesktopLazyImportsTests(unittest.TestCase):
    def test_browsing_imports_do_not_load_recognition(self):
        code = """
import sys
from bd2_fishing.app.desktop import DesktopServices
from bd2_fishing.ui.window import FishingApp
from bd2_fishing import bootstrap
for name in ('cv2', 'onnxruntime', 'rapidocr', 'bd2_fishing.app.session'):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_task_imports_runner_and_forwards_call(self):
        runner = Mock(return_value="completed")
        with patch.dict(sys.modules, {"bd2_fishing.app.session": SimpleNamespace(run_once=runner)}):
            self.assertEqual(bootstrap._run_task("config", mode="targets"), "completed")
        runner.assert_called_once_with("config", mode="targets")


if __name__ == "__main__":
    unittest.main()
