"""工作树调试配置回归，不连接游戏或发送输入。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import record_qte_session as tool


class DebugConfigTests(unittest.TestCase):
    def test_worktree_without_deployed_config_uses_its_source_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "auto_fishing-dev"
            root.mkdir()
            path = root / "config.ini"
            path.write_text("[backpack]\n[ocr]\n[diagnostics]\n", encoding="utf-8")
            with patch.object(tool, "ROOT", root):
                config, selected = tool.load_debug_config()
            self.assertEqual(selected, path.resolve())
            self.assertTrue(config.has_section("diagnostics"))

    def test_explicit_config_is_not_modified_by_process_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user.ini"
            original = "[backpack]\nauto_clear_enabled=true\n[ocr]\n[diagnostics]\n"
            path.write_text(original, encoding="utf-8")
            config, selected = tool.load_debug_config(path)
            config.set("backpack", "auto_clear_enabled", "false")
            self.assertEqual(selected, path.resolve())
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_missing_explicit_config_fails_before_gameplay(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                tool.load_debug_config(Path(directory) / "missing.ini")


if __name__ == "__main__":
    unittest.main()
