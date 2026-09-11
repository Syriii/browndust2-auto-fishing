"""用模拟时钟验证真实等待逻辑，不导入输入驱动或操作游戏。"""

import ast
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from bd2_fishing.game.fishing.cast_feedback import CastPositionBlocked
from bd2_fishing.runtime import control as run_control
from tests.support import ROOT


class BiteWaitTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.cast_at = None
        self.diagnostics = Mock()
        self.press = Mock()
        self.recover = Mock(side_effect=self.recovery)
        self.backpack = Mock(return_value=False)
        self.timeout_recover = Mock(side_effect=self.timeout_recovery)
        self.bot = SimpleNamespace(
            _record_incident=Mock(),
            _recover_bite_timeout=self.timeout_recover,
            hook_diagnostics=self.diagnostics,
            bite_pixel_threshold=212,
            region=None,
            hook_pos=None,
            selected_location_name="深渊巨口",
            config=None,
            ocr_context=None,
            auto_clear_backpack=True,
            hook_yellow_range=SimpleNamespace(lower=None, upper=None),
            _sleep_loop=lambda: self.advance(0.25),
        )
        self.namespace = {
            "time": SimpleNamespace(monotonic=lambda: self.now),
            "BITE_TIMEOUT_SECONDS": 15,
            "log": Mock(),
            "print": Mock(),
            "run_control": run_control,
            "cv2": cv2,
            "vision": SimpleNamespace(create_color_mask=lambda *a, **k: self.mask()),
            "fishing_actions": SimpleNamespace(
                recover_from_timeout=self.recover,
                clear_backpack=lambda *a: self.advance(20),
                cast_rod=self.cast,
            ),
            "cast_feedback": SimpleNamespace(
                check_backpack_if_full=self.backpack, CastPositionBlocked=CastPositionBlocked
            ),
            "pydirectinput": SimpleNamespace(press=self.press),
        }
        self.namespace["inventory_actions"] = self.namespace["fishing_actions"]
        source = ROOT / "bd2_fishing" / "app" / "fishing_task.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "wait_for_bite"
        )
        module = ast.Module(
            body=[
                ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                method,
            ],
            type_ignores=[],
        )
        exec(compile(ast.fix_missing_locations(module), str(source), "exec"), self.namespace)

    def advance(self, seconds):
        self.now += seconds
        if self.now > 60:
            self.fail("等待未在模拟时限内结束")

    def cast(self):
        self.advance(0.5)
        self.cast_at = self.now

    def timeout_recovery(self):
        self.advance(3)
        self.cast()
        return False

    def recovery(self, region):
        if self.recover.call_count > 1:
            self.fail("新抛竿未获得完整等待时间，提前再次恢复")
        self.advance(3)
        self.cast()

    def mask(self):
        # 下一轮接近 15 秒时才上钩，确保恢复或清包不侵占等待窗口。
        count = 300 if self.cast_at is not None and self.now - self.cast_at >= 14.75 else 0
        return np.full((1, count or 1), 255 if count else 0, dtype=np.uint8)

    def wait(self):
        capture = Mock(grab=Mock(return_value=np.zeros((2, 2, 3), dtype=np.uint8)))
        self.namespace["wait_for_bite"](self.bot, capture)

    def test_recovery_gets_full_wait_and_rechecks_backpack_after_cast(self):
        checked_at = []
        self.backpack.side_effect = lambda *a: checked_at.append(self.now) or False
        self.wait()
        self.timeout_recover.assert_called_once()
        self.recover.assert_not_called()
        self.press.assert_called_once_with("space")
        self.assertIn(self.cast_at, checked_at)

    def test_slow_backpack_cleanup_does_not_trigger_immediate_recovery(self):
        self.backpack.side_effect = [True] + [False] * 10
        self.wait()
        self.recover.assert_not_called()
        self.diagnostics.save_timeout.assert_not_called()
        self.press.assert_called_once_with("space")

    def test_backpack_recast_discards_previous_window_diagnostics(self):
        self.backpack.side_effect = [False, True] + [False] * 10
        observations = []
        self.diagnostics.reset.side_effect = observations.clear
        self.diagnostics.observe.side_effect = lambda *a: observations.append(self.now)
        self.wait()
        self.assertTrue(observations)
        self.assertTrue(all(timestamp >= self.cast_at for timestamp in observations))

    def test_disabled_cleanup_stops_on_full_backpack_without_input(self):
        self.bot.auto_clear_backpack = False
        self.backpack.return_value = True
        clear = Mock()
        self.namespace["fishing_actions"].clear_backpack = clear
        with self.assertRaises(run_control.RunStopped):
            self.wait()
        clear.assert_not_called()
        self.press.assert_not_called()
        self.recover.assert_not_called()
        self.assertIsNone(self.cast_at)

    def test_disabled_cleanup_still_allows_fishing_when_not_full(self):
        self.bot.auto_clear_backpack = False
        self.cast_at = 0
        self.wait()
        self.press.assert_called_once_with("space")
        self.recover.assert_not_called()

    def test_blocked_cast_recovers_immediately_and_gets_full_new_wait(self):
        self.bot.auto_clear_backpack = False
        checked_at = []

        def feedback(*args):
            checked_at.append(self.now)
            if len(checked_at) == 1:
                raise CastPositionBlocked("当前位置无法抛竿")
            return False

        self.backpack.side_effect = feedback
        clear = Mock()
        self.namespace["fishing_actions"].clear_backpack = clear
        self.wait()
        self.recover.assert_called_once()
        self.assertLess(self.cast_at, 15)
        self.assertIn(self.cast_at, checked_at)
        self.assertGreaterEqual(self.now - self.cast_at, 14.75)
        self.assertEqual(self.diagnostics.reset.call_count, 2)
        self.diagnostics.save_timeout.assert_not_called()
        self.press.assert_called_once_with("space")
        clear.assert_not_called()

    def test_persistent_blocked_position_stops_after_one_recovery(self):
        self.backpack.side_effect = CastPositionBlocked("当前位置无法抛竿")
        with self.assertRaisesRegex(run_control.RunStopped, "自动移动并重抛后仍无法抛竿"):
            self.wait()
        self.recover.assert_called_once()
        self.assertEqual(self.backpack.call_count, 2)
        self.press.assert_not_called()

    def test_stop_during_position_recovery_does_not_resume(self):
        self.backpack.side_effect = CastPositionBlocked("当前位置无法抛竿")
        self.recover.side_effect = run_control.RunStopped()
        with self.assertRaises(run_control.RunStopped):
            self.wait()
        self.recover.assert_called_once()
        self.assertEqual(self.backpack.call_count, 1)
        self.press.assert_not_called()


if __name__ == "__main__":
    unittest.main()
