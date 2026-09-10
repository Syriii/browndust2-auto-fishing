"""验证包迁移后配置、资源与发布清单仍指向同一项目。"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

from bd2_fishing.game.fishing import feedback as qte_feedback
from bd2_fishing.infrastructure import paths as paths
from bd2_fishing.infrastructure import settings as settings
from scripts import build_release
from tests.support import DEFAULT_CONFIG, ROOT


class ProjectLayoutTests(unittest.TestCase):
    def test_fresh_build_creates_metadata_outside_source_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy2(ROOT / "setup.py", root / "setup.py")
            (root / "example").mkdir(parents=True)
            (root / "example/__init__.py").write_text("", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                '[build-system]\nrequires=["setuptools>=68"]\nbuild-backend="setuptools.build_meta"\n'
                '[project]\nname="build-location-test"\nversion="0.0.0"\n'
                '[tool.setuptools.packages.find]\nwhere=["."]\ninclude=["example*"]\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-B",
                    "-c",
                    "from setuptools.build_meta import get_requires_for_build_editable, build_wheel; "
                    "get_requires_for_build_editable(); build_wheel('.local/wheels')",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual([path.name for path in (root / "example").iterdir()], ["__init__.py"])
            self.assertFalse(list(root.glob("*.egg-info")))
            self.assertTrue((root / "build/build_location_test.egg-info/PKG-INFO").is_file())

    def test_source_config_and_resources_do_not_follow_working_directory(self):
        with tempfile.TemporaryDirectory() as temporary, chdir(temporary):
            self.assertEqual(Path(paths.get_base_path()), ROOT / ".local")
            self.assertEqual(Path(paths.get_log_path()), ROOT / ".local/logs")
            self.assertEqual(Path(paths.get_diagnostics_path()), ROOT / ".local/diagnostics")
            self.assertEqual(
                Path(paths.get_resource_path("models/test.onnx")), ROOT / "models/test.onnx"
            )
            self.assertFalse((Path(temporary) / "config.ini").exists())

    def test_config_creation_uses_package_defaults_and_preserves_existing_file(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(settings, "get_base_path", return_value=temporary),
            patch.object(settings, "get_config_path", return_value=Path(temporary) / "config.ini"),
        ):
            config = settings.read_ini()
            self.assertTrue(config.has_section("hook"))
            path = Path(temporary) / "config.ini"
            self.assertEqual(
                path.read_text(encoding="utf-8-sig"), DEFAULT_CONFIG.read_text(encoding="utf-8-sig")
            )
            custom = b"; user comment\n[backpack]\nauto_clear_enabled = false\n"
            path.write_bytes(custom)
            self.assertFalse(settings.read_ini().getboolean("backpack", "auto_clear_enabled"))
            self.assertEqual(path.read_bytes(), custom)

    def test_frozen_config_is_beside_executable_and_resources_are_bundled(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary).resolve()
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(app / "BD2_AutoFishing.exe")),
                patch.object(sys, "_MEIPASS", str(app / "_internal"), create=True),
            ):
                self.assertEqual(Path(paths.get_base_path()), app)
                self.assertEqual(paths.get_config_path(), app / "config/config.ini")
                self.assertEqual(Path(paths.get_log_path()), app / "logs")
                self.assertEqual(Path(paths.get_diagnostics_path()), app / "screenshots")
                self.assertEqual(
                    Path(paths.get_resource_path("models/test.onnx")),
                    app / "_internal" / "models" / "test.onnx",
                )

    def test_build_collects_templates_at_the_path_expected_by_packaged_modules(self):
        import os

        with patch.object(build_release, "gather_copy_metadata_targets", return_value=[]):
            command = build_release.build_pyinstaller_command(include_nvidia=False, model_files=[])
        data = [
            command[i + 1].split(os.pathsep, 1)
            for i, arg in enumerate(command)
            if arg == "--add-data"
        ]
        templates = Path(qte_feedback.__file__).with_name("assets")
        self.assertIn([str(templates), "bd2_fishing/game/fishing/assets"], data)
        self.assertTrue((templates / "settlement_close.png").is_file())
        self.assertIn([str(DEFAULT_CONFIG), "bd2_fishing/resources"], data)
        self.assertEqual(command[command.index("--distpath") + 1], str(ROOT / "dist"))
        self.assertEqual(command[command.index("--workpath") + 1], str(ROOT / "build/pyinstaller"))


if __name__ == "__main__":
    unittest.main()
