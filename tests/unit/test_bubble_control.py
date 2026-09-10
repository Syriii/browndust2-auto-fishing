"""泡泡球原图、绿条负例与混合目标输入；不连接游戏。"""

import configparser
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from bd2_fishing.game.fishing import qte
from bd2_fishing.game.fishing.mechanics.bubbles import BubbleController
from bd2_fishing.game.fishing.mechanics.regions import read_mechanism_regions
from bd2_fishing.infrastructure.settings import DEFAULT_CONFIG_CONTENT
from bd2_fishing.runtime.control import RunStopped
from bd2_fishing.runtime.geometry import Rect

FIXTURES = Path(__file__).parents[1] / "fixtures/qte_control"


class BubbleImageTests(unittest.TestCase):
    def test_two_real_sequences_are_bubbles_not_green_holds_at_three_scales(self):
        for path in sorted(FIXTURES.glob("bubble_part*.png")):
            raw = cv2.imread(str(path))[21:40, 68:312]
            for scale in (0.925, 1, 1.5):
                frame = cv2.resize(raw, None, fx=scale, fy=scale)
                regions = read_mechanism_regions(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
                self.assertFalse(regions.green_present, (path.name, scale))
                self.assertEqual(len(regions.bubble_spans), 1, (path.name, scale))
                left, right = regions.bubble_spans[0]
                self.assertLess(left, round(57 * scale))
                self.assertGreater(right, round(57 * scale))

    def test_true_green_teeth_purple_and_blue_do_not_authorize_bubble_press(self):
        for name in (
            "green_mixed_000.png",
            "green_mixed_001.png",
            "green_only_058.png",
            "red_teeth_11.png",
            "purple_content.png",
            "blue_only_0.png",
        ):
            raw = cv2.imread(str(FIXTURES / name))
            raw = raw[117:136, 86:330] if name.startswith("green") else raw[21:40, 68:312]
            regions = read_mechanism_regions(cv2.cvtColor(raw, cv2.COLOR_BGR2HSV))
            self.assertFalse(regions.bubble_spans, name)
            if name.startswith("green"):
                self.assertTrue(regions.green_present)

    def test_bubble_and_real_green_can_coexist(self):
        raw = cv2.imread(str(FIXTURES / "bubble_part1_005.png"))[21:40, 68:312]
        hsv = cv2.cvtColor(raw, cv2.COLOR_BGR2HSV)
        hsv[:, 180:220] = (60, 230, 230)
        regions = read_mechanism_regions(hsv)
        self.assertTrue(regions.green_present)
        self.assertEqual(len(regions.bubble_spans), 1)


class BubbleStateTests(unittest.TestCase):
    def test_single_press_requires_confirmed_center_and_real_absence_to_rearm(self):
        machine = BubbleController()
        span = ((40, 70),)
        self.assertFalse(machine.observe(span, 10, 0))
        self.assertTrue(machine.observe(span, 56, 0.02))
        self.assertFalse(machine.observe(span, 56, 0.04))
        machine.observe((), None, 0.06)
        self.assertFalse(machine.observe(span, 56, 0.08))
        machine.observe((), None, 0.1)
        machine.observe((), None, 0.3)
        machine.observe((), None, 0.42)
        self.assertFalse(machine.observe(span, 56, 0.44))
        self.assertTrue(machine.observe(span, 56, 0.46))

    def test_unknown_pointer_blocker_or_gap_never_grants_a_press(self):
        for cursor, blocked in ((None, False), (56, True), (40, False), (80, False)):
            machine = BubbleController()
            for stamp in (0, 0.02, 0.04):
                self.assertFalse(machine.observe(((40, 70),), cursor, stamp, blocked=blocked))
        machine = BubbleController()
        machine.observe(((40, 70),), 56, 0)
        self.assertFalse(machine.observe(((40, 70),), 56, 1))
        machine.invalidate_observation()
        self.assertFalse(machine.observe(((40, 70),), 56, 1.02))


class BubbleStrategyTests(unittest.TestCase):
    def strategy(self, cls):
        config = configparser.ConfigParser()
        config.read_string(DEFAULT_CONFIG_CONTENT)
        strategy = cls(config, Rect(0, 0, 945, 532))
        strategy._start_feedback = Mock()
        strategy._press_qte = Mock()
        strategy._time_bar_visible_from_masks = Mock(return_value=True)
        if cls is qte.AbyssMawQTEStrategy:
            strategy._blocker_detector.read = Mock(return_value=None)
        return strategy

    def run_frames(self, strategy, frames):
        clock = [0.0]

        def step():
            clock[0] += 0.02
            if clock[0] >= len(frames) * 0.02 - 0.001:
                raise RunStopped("offline replay complete")

        strategy._sleep_loop = step
        strategy._grab_qte_frames = Mock(side_effect=frames)
        with patch.object(qte.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(RunStopped):
                strategy.play_qte(Mock())
        return strategy._press_qte.call_args_list

    def test_bubble_has_one_native_press_and_never_holds(self):
        raw = cv2.imread(str(FIXTURES / "bubble_part1_005.png"))
        frame = cv2.cvtColor(raw, cv2.COLOR_BGR2HSV)
        for cls in (qte.FrostStraitQTEStrategy, qte.AbyssMawQTEStrategy):
            strategy = self.strategy(cls)
            # 显式位置仅验证动作接线；不冒充该球体遮挡帧已经识别出光标。
            strategy._find_cursor_x = Mock(return_value=56)
            with patch.object(qte.pydirectinput, "qte_key_down") as down:
                calls = self.run_frames(strategy, [frame] * 4)
            self.assertEqual([c.args[0] for c in calls], ["bubble_target"])
            down.assert_not_called()

    def test_real_blue_only_frames_and_bubble_overlay_keep_blue_fallback(self):
        frames = [
            cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2HSV)
            for name in ("blue_only_0.png", "blue_only_1.png", "blue_only_2.png")
        ]
        ball = cv2.cvtColor(cv2.imread(str(FIXTURES / "bubble_part1_005.png")), cv2.COLOR_BGR2HSV)
        for cls in (qte.FrostStraitQTEStrategy, qte.AbyssMawQTEStrategy):
            for overlay in (False, True):
                sequence = [frame.copy() for frame in frames]
                if overlay:
                    # 真实球体叠加在另一组真实蓝条序列：检验其金色边缘不伪造黄条。
                    for frame in sequence:
                        frame[21:40, 110:144] = ball[21:40, 110:144]
                calls = self.run_frames(self.strategy(cls), sequence)
                self.assertEqual(
                    [c.args[0] for c in calls], ["blue_fallback"], (cls.__name__, overlay)
                )

    def test_blue_flicker_and_missing_frame_do_not_fire_in_either_strategy(self):
        hsv = np.zeros((30, 200, 3), np.uint8)
        hsv[:, 80:120] = (99, 200, 255)
        hsv[:, 100] = (0, 0, 255)
        for cls in (qte.FrostStraitQTEStrategy, qte.AbyssMawQTEStrategy):
            for frames in ([hsv], [hsv, None, hsv]):
                strategy = self.strategy(cls)
                strategy._split_roi_and_time = lambda frame: (frame, frame)
                self.assertFalse(self.run_frames(strategy, frames))
