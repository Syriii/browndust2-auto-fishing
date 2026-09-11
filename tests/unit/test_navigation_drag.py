"""地图拖动取消与错误释放；所有原生鼠标调用均替换为测试桩。"""

from unittest import TestCase
from unittest.mock import patch

from bd2_fishing.infrastructure.windows import input as game_input
from bd2_fishing.runtime.control import RunStopped


class NavigationDragTests(TestCase):
    def test_cancel_releases_held_mouse(self):
        with (
            patch.object(game_input, "moveTo") as move,
            patch.object(game_input._input, "mouseDown") as down,
            patch.object(game_input._input, "mouseUp") as up,
            patch.object(game_input.run_control, "sleep", side_effect=RunStopped("cancel")),
        ):
            with self.assertRaises(RunStopped):
                game_input.drag_between((100, 100), (400, 100))
            down.assert_called_once()
            up.assert_called_once()
            self.assertEqual(move.call_count, 1)

    def test_failed_move_releases_held_mouse(self):
        with (
            patch.object(game_input, "moveTo", side_effect=[None, RuntimeError("lost window")]),
            patch.object(game_input._input, "mouseDown"),
            patch.object(game_input._input, "mouseUp") as up,
            patch.object(game_input.run_control, "sleep"),
        ):
            with self.assertRaises(RuntimeError):
                game_input.drag_between((100, 100), (400, 100))
            up.assert_called_once()

    def test_complete_drag_reaches_endpoint_and_releases(self):
        with (
            patch.object(game_input, "moveTo") as move,
            patch.object(game_input._input, "mouseDown"),
            patch.object(game_input._input, "mouseUp") as up,
            patch.object(game_input.run_control, "sleep"),
        ):
            game_input.drag_between((-500, 100), (-100, 100))
            move.assert_called_with(-100, 100, _pause=False)
            up.assert_called_once()

    def test_invalid_duration_sends_no_input(self):
        with patch.object(game_input, "moveTo") as move:
            for duration in (0, -1, float("nan"), 5):
                with self.assertRaises(ValueError):
                    game_input.drag_between((100, 100), (400, 100), duration=duration)
            move.assert_not_called()
