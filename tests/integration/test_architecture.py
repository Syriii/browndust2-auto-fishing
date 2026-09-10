"""验证职责边界与真实的可替换能力，不依赖游戏窗口。"""

import ast
import configparser
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bd2_fishing.app.desktop import DesktopServices
from bd2_fishing.app.fishing_task import FishingBot
from bd2_fishing.infrastructure.settings import DEFAULT_CONFIG_CONTENT
from bd2_fishing.runtime.geometry import Rect
from scripts.checks.check_architecture import check_package
from tests.support import ROOT

PACKAGE = ROOT / "bd2_fishing"


class ArchitectureTests(unittest.TestCase):
    def test_complete_package_obeys_boundaries_and_has_no_static_import_cycles(self):
        errors, count = check_package()
        self.assertGreater(count, 0)
        self.assertEqual(errors, [])

    def test_dependency_checker_rejects_alias_imports_and_relative_cycles(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "bd2_fishing"
            (package / "runtime").mkdir(parents=True)
            (package / "game").mkdir()
            (package / "runtime/a.py").write_text(
                "from bd2_fishing import game\nfrom . import b\n", encoding="utf-8"
            )
            (package / "runtime/b.py").write_text("from . import a\n", encoding="utf-8")
            (package / "game/__init__.py").write_text("", encoding="utf-8")
            errors, _ = check_package(package)
            self.assertTrue(any("Forbidden dependency" in item for item in errors))
            self.assertTrue(any("Import cycle" in item for item in errors))

    def test_runtime_and_ui_do_not_import_concrete_device_implementations(self):
        for folder, forbidden in (
            (
                "runtime",
                (
                    "bd2_fishing.infrastructure",
                    "bd2_fishing.app",
                    "bd2_fishing.game",
                    "bd2_fishing.ui",
                ),
            ),
            ("ui", ("bd2_fishing.infrastructure", "bd2_fishing.game")),
        ):
            for path in (PACKAGE / folder).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                for node in ast.walk(tree):
                    modules = (
                        [node.module or ""]
                        if isinstance(node, ast.ImportFrom)
                        else (
                            [alias.name for alias in node.names]
                            if isinstance(node, ast.Import)
                            else []
                        )
                    )
                    for module in modules:
                        self.assertFalse(module.startswith(forbidden), (path, module))

    def test_production_cannot_import_experimental_tools_or_test_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "bd2_fishing"
            (package / "app").mkdir(parents=True)
            (package / "app/task.py").write_text(
                "from scripts.live import record_qte_session\nfrom tests import support\n",
                encoding="utf-8",
            )
            errors, _ = check_package(package)
            self.assertTrue(any("scripts.live" in item for item in errors))
            self.assertTrue(any("tests.support" in item for item in errors))

    def test_rules_and_catalog_import_without_windows_or_ocr_runtime(self):
        code = """
import importlib.abc, sys
class BlockNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'win32gui', 'win32api', 'dxcam', 'pydirectinput', 'rapidocr', 'onnxruntime', 'tkinter'}:
            raise AssertionError('Unexpected native import: ' + fullname)
sys.meta_path.insert(0, BlockNative())
from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.game.fishing.feedback_rules import OutcomeTracker
from bd2_fishing.game.fishing.settlement_rules import classify_settlement
from bd2_fishing.game.observation import OCRContext
from bd2_fishing.game.fishing.recognition import FeedbackMatcher
from bd2_fishing.perception.ocr import get_result_from_ocr
from bd2_fishing.game.fishing.mechanics.policy import MechanismPolicy
from bd2_fishing.game.fishing.mechanics.blockers import BlockerDetector
assert list(FishingLocation)
assert OutcomeTracker()
assert MechanismPolicy()
"""
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", "-c", code],
            cwd=tempfile.gettempdir(),
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_every_new_mechanic_is_checked_without_adding_its_filename(self):
        for statement in (
            "from bd2_fishing.infrastructure.windows import input",
            "from bd2_fishing.game.fishing import qte",
            "from ..feedback import FeedbackSession",
        ):
            for filename in ("future_skill.py", "__init__.py"):
                with (
                    self.subTest(statement=statement, filename=filename),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    package = Path(directory) / "bd2_fishing"
                    folder = package / "game/fishing/mechanics"
                    folder.mkdir(parents=True)
                    (folder / filename).write_text(statement, encoding="utf-8")
                    errors, _ = check_package(package)
                    self.assertTrue(errors, statement)

    def test_capture_factory_is_used_without_creating_native_camera(self):
        config = configparser.ConfigParser()
        config.read_string(DEFAULT_CONFIG_CONTENT)
        capture = Mock()
        factory = Mock(
            return_value=Mock(
                __enter__=Mock(return_value=capture), __exit__=Mock(return_value=False)
            )
        )
        bot = FishingBot(
            config, Rect(0, 0, 875, 492), Mock(), interactive=False, capture_factory=factory
        )
        expected = RuntimeError("stop before any game action")
        with (
            patch("bd2_fishing.app.fishing_task.window.WindowGuard"),
            patch("bd2_fishing.app.fishing_task.DxCameraCapture") as native,
            patch.object(bot, "choose_strategy", side_effect=expected) as choose,
        ):
            with self.assertRaisesRegex(RuntimeError, "stop before"):
                bot.run()
        native.assert_not_called()
        factory.assert_called_once_with(output_color="BGR", window_region=bot.region)
        choose.assert_called_once_with(capture)

    def test_desktop_service_preserves_unmanaged_settings_and_uses_injected_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            path.write_text(
                "; keep comment\n[app]\nlocation=自动识别\n[custom]\nvalue=keep\n", encoding="utf-8"
            )
            release = Mock()
            service = DesktopServices(config_path=path, release_inputs=release)
            service.save_settings({"app": {"location": "烟波湖"}})
            self.assertEqual(service.load_settings().get("custom", "value"), "keep")
            self.assertIn("; keep comment", path.read_text(encoding="utf-8-sig"))
            task = service.create_task(Mock())
            self.assertIs(task.release_inputs, release)
            preview = service.create_task(Mock(), preview=True)
            preview.release_inputs()
            release.assert_not_called()
