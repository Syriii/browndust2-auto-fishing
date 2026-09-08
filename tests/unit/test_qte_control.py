"""QTE 输入条件回归：真实失败原图与连续帧；不连接游戏。"""

import configparser
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from bd2_fishing.game.fishing import qte
from bd2_fishing.infrastructure import settings
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class QTEControlTests(unittest.TestCase):
    fixtures = Path(__file__).parents[1] / "fixtures" / "qte_control"

    def make_strategy(self, cls=qte.FrostStraitQTEStrategy):
        config = configparser.ConfigParser()
        config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        strategy = cls(config, Rect(1, 460, 946, 992))
        strategy._start_feedback = Mock()
        strategy._sleep_loop = Mock(side_effect=control.RunStopped("sample finished"))
        return strategy

    def test_real_missing_cursor_miss_frames_never_send_input(self):
        fixtures = Path(__file__).parents[1] / "fixtures" / "qte_control"
        for name in ("no_cursor_5.png", "no_cursor_9.png"):
            with self.subTest(name=name):
                frame = cv2.imread(str(fixtures / name))
                self.assertIsNotNone(frame)
                strategy = self.make_strategy()
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                # 取证保存的是完整决策 ROI，使用正式裁剪和颜色规则。
                _, qte_hsv = strategy._split_roi_and_time(hsv)
                self.assertIsNone(strategy._find_cursor_x(qte_hsv))
                strategy._time_bar_visible_from_masks = Mock(return_value=True)
                with patch.object(qte.pydirectinput, "press") as press:
                    with self.assertRaises(control.RunStopped):
                        strategy.play_qte(Mock(grab=Mock(return_value=frame)))
                press.assert_not_called()

    def run_frames(self, strategy, frames):
        strategy._grab_qte_frames = Mock(side_effect=frames)
        strategy._sleep_loop = Mock(
            side_effect=[None] * (len(frames) - 1) + [control.RunStopped("sample finished")]
        )
        strategy._time_bar_visible_from_masks = Mock(return_value=True)
        strategy._press_qte = Mock()
        with self.assertRaises(control.RunStopped):
            strategy.play_qte(Mock())
        return strategy._press_qte.call_args_list

    def test_real_blue_only_sequence_uses_blue_once_and_outside_never_fires(self):
        frames = [
            cv2.cvtColor(cv2.imread(str(self.fixtures / name)), cv2.COLOR_BGR2HSV)
            for name in ("blue_only_0.png", "blue_only_1.png", "blue_only_2.png")
        ]
        calls = self.run_frames(self.make_strategy(), frames)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args, ("blue_fallback",))
        outside = cv2.cvtColor(
            cv2.imread(str(self.fixtures / "blue_outside.png")), cv2.COLOR_BGR2HSV
        )
        self.assertFalse(self.run_frames(self.make_strategy(), [outside] * 3))

    def test_red_teeth_images_do_not_trigger_blind_ice_press(self):
        for name in ("red_teeth_4.png", "red_teeth_11.png", "red_teeth_23.png"):
            with self.subTest(name=name):
                hsv = cv2.cvtColor(cv2.imread(str(self.fixtures / name)), cv2.COLOR_BGR2HSV)
                calls = self.run_frames(self.make_strategy(), [hsv] * 3)
                self.assertFalse(calls)

    def test_blue_fallback_rejects_flicker_unknown_gray_green_and_red_overlap(self):
        def make_frame(color):
            hsv = np.zeros((30, 200, 3), np.uint8)
            hsv[:, 80:120] = color
            hsv[:, 100] = (0, 0, 255)
            return hsv

        blue = make_frame((99, 200, 255))
        red = blue.copy()
        red[:, 104:110] = (175, 200, 200)
        for frames in (
            [blue],
            [blue, None, blue],
            [make_frame((0, 0, 100))] * 3,
            [make_frame((60, 255, 255))] * 3,
            [red] * 3,
        ):
            with self.subTest(frames=len(frames)):
                strategy = self.make_strategy()
                strategy._split_roi_and_time = lambda hsv: (hsv, hsv)
                self.assertFalse(self.run_frames(strategy, frames))

    def test_yellow_priority_and_red_away_from_cursor_keep_normal_input(self):
        hsv = np.zeros((30, 200, 3), np.uint8)
        hsv[:, 80:120] = (99, 200, 255)
        hsv[:, 150:180] = (25, 255, 255)
        hsv[:, 100] = (0, 0, 255)
        strategy = self.make_strategy()
        strategy._split_roi_and_time = lambda hsv: (hsv, hsv)
        self.assertFalse(self.run_frames(strategy, [hsv] * 3))
        hsv[:, 100] = (99, 200, 255)
        hsv[:, 160] = (0, 0, 255)
        hsv[:, 20:35] = (175, 200, 200)
        calls = self.run_frames(strategy, [hsv] * 3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args, ("yellow_overlap",))

    def test_strategy_requires_observed_exit_even_across_missing_frames(self):
        for cls in (qte.FrostStraitQTEStrategy, qte.AbyssMawQTEStrategy):
            with self.subTest(strategy=cls.__name__):
                strategy = self.make_strategy(cls)

                def frame(cursor, *, target=True):
                    hsv = np.zeros((30, 200, 3), np.uint8)
                    if target:
                        hsv[:, 80:110] = (25, 255, 255)
                    if cursor is not None:
                        hsv[:, cursor] = (0, 0, 255)
                    return hsv

                frames = [
                    frame(90),
                    frame(90),
                    None,
                    frame(None),
                    frame(90, target=False),
                    frame(90),
                    frame(20),
                    frame(90),
                ]
                strategy._grab_qte_frames = Mock(side_effect=frames)
                strategy._split_roi_and_time = lambda hsv: (hsv, hsv)
                strategy._time_bar_visible_from_masks = Mock(return_value=True)
                strategy._sleep_loop = Mock(
                    side_effect=[None] * (len(frames) - 1) + [control.RunStopped("end")]
                )
                if cls is qte.AbyssMawQTEStrategy:
                    strategy._blocker_rect = Mock(return_value=None)
                with patch.object(qte.pydirectinput, "press") as press:
                    with self.assertRaises(control.RunStopped):
                        strategy.play_qte(Mock())
                    self.assertEqual(press.call_count, 2)


if __name__ == "__main__":
    unittest.main()
