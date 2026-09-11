"""区域随机落点、左右屏坐标及输入保护；不操作真实桌面。"""

import random
from unittest import TestCase
from unittest.mock import Mock, patch

from bd2_fishing.infrastructure.windows import input as game_input
from bd2_fishing.runtime import control
from bd2_fishing.runtime.click_area import random_point
from bd2_fishing.runtime.geometry import Rect


class ClickAreaTests(TestCase):
    def test_all_points_stay_inside_inset_and_are_not_fixed(self):
        rng = random.Random(20260911)
        for bounds in (Rect(100, 200, 200, 240), Rect(-1200, -200, -1100, -160)):
            with patch("bd2_fishing.runtime.click_area.random.randint", side_effect=rng.randint):
                points = {random_point(bounds) for _ in range(300)}
            self.assertGreater(len(points), 100)
            for x, y in points:
                self.assertTrue(bounds.left + 20 <= x < bounds.right - 20)
                self.assertTrue(bounds.top + 8 <= y < bounds.bottom - 8)

    def test_tiny_area_and_zero_margin_respect_exclusive_edges(self):
        self.assertEqual(random_point(Rect(-1, 3, 0, 4)), (-1, 3))
        with patch("bd2_fishing.runtime.click_area.random.randint", side_effect=lambda a, b: b):
            self.assertEqual(random_point(Rect(10, 20, 12, 22), inset_ratio=0), (11, 21))

    def test_invalid_bounds_or_margin_never_send_input(self):
        with patch.object(game_input, "click") as click:
            for bounds in (Rect(0, 0, 0, 2), Rect(3, 0, 1, 2), Rect(0.5, 0, 2, 3)):
                with self.assertRaises(ValueError):
                    game_input.click_in_rect(bounds)
            for margin in (-0.1, 0.5, float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    game_input.click_in_rect(Rect(0, 0, 10, 10), inset_ratio=margin)
            click.assert_not_called()

    def test_area_click_uses_existing_guarded_input_once_and_returns_actual_point(self):
        with (
            patch.object(game_input, "_move_virtual") as move,
            patch.object(game_input._input, "click") as click,
            patch.object(game_input, "random_point", return_value=(-102, 300)),
        ):
            guard = Mock()
            with control.use_input_guard(guard):
                point = game_input.click_in_rect(Rect(-110, 290, -90, 320))
            self.assertEqual(point, (-102, 300))
            move.assert_called_once_with(-102, 300)
            click.assert_called_once()
            self.assertGreaterEqual(guard.call_count, 3)

    def test_stop_before_move_and_focus_loss_before_click_prevent_native_click(self):
        with (
            patch.object(game_input, "_move_virtual") as move,
            patch.object(game_input._input, "click") as click,
        ):
            stopped = control.RunControl()
            stopped.stopped.set()
            with control.use_control(stopped), self.assertRaises(control.RunStopped):
                game_input.click_in_rect(Rect(0, 0, 40, 40))
            move.assert_not_called()
            guard = Mock(side_effect=[None, None, control.RunStopped("focus")])
            with control.use_input_guard(guard), self.assertRaises(control.RunStopped):
                game_input.click_in_rect(Rect(0, 0, 40, 40))
            move.assert_called_once()
            click.assert_not_called()
