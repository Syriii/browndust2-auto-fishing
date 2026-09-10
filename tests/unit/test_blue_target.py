"""蓝区边界、光标光晕与真实原图回归；不访问游戏。"""

import configparser
import unittest
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np

from bd2_fishing.game.fishing.mechanics.blue_target import read_blue_target
from bd2_fishing.game.fishing.qte import AbyssMawQTEStrategy, FrostStraitQTEStrategy
from bd2_fishing.game.fishing.trigger_rules import TargetEntryTrigger
from bd2_fishing.infrastructure.settings import DEFAULT_CONFIG_CONTENT
from bd2_fishing.runtime.control import RunStopped
from bd2_fishing.runtime.geometry import Rect


class BlueTargetTests(unittest.TestCase):
    def test_both_outer_edges_and_margin_are_never_pressable(self):
        mask = np.zeros((19, 200), np.uint8)
        mask[:, 80:120] = 255
        for x in (70, 75, 79, 80, 119, 120, 125, 129):
            self.assertIsNot(read_blue_target(mask, x).overlap, True, x)
        for x in (81, 100, 118):
            self.assertTrue(read_blue_target(mask, x).overlap, x)

    def test_only_narrow_cursor_hole_is_repaired_and_obstacles_never_bridged(self):
        mask = np.zeros((19, 200), np.uint8)
        mask[:, 80:120] = 255
        mask[:, 96:105] = 0
        reading = read_blue_target(mask, 100)
        self.assertTrue(reading.overlap)
        self.assertEqual(reading.repaired_cursor_gap, (96, 105))
        self.assertEqual(reading.safe_spans, ((81, 119),))
        self.assertIsNone(read_blue_target(mask, None).repaired_cursor_gap)
        blocked = np.zeros(200, bool)
        blocked[102] = True
        self.assertIsNot(read_blue_target(mask, 100, blocked=blocked).overlap, True)
        mask[:, 92:109] = 0
        self.assertIsNone(read_blue_target(mask, 100).overlap)

    def test_border_glow_sparse_dots_and_one_column_are_not_targets(self):
        for kind in ("border", "dots", "line"):
            mask = np.zeros((19, 200), np.uint8)
            if kind == "border":
                mask[[0, 18], 40:160] = 255
            elif kind == "dots":
                mask[8, 40:160] = 255
            else:
                mask[:, 100] = 255
            self.assertFalse(read_blue_target(mask, 100).safe_spans)

    def test_current_shrinking_target_replaces_old_bounds(self):
        mask = np.zeros((19, 200), np.uint8)
        mask[:, 60:150] = 255
        self.assertTrue(read_blue_target(mask, 140).overlap)
        mask[:, 125:] = 0
        self.assertFalse(read_blue_target(mask, 140).overlap)

    def test_blocker_range_cannot_clamp_a_cursor_into_the_target(self):
        mask = np.zeros((19, 200), np.uint8)
        mask[:, 80:120] = 255
        self.assertIsNone(read_blue_target(mask, 101, active_range=(0, 100)).overlap)
        self.assertIsNot(read_blue_target(mask, 100, active_range=(0, 100)).overlap, True)

    def test_margin_and_unknown_hole_do_not_rearm_same_overlap(self):
        trigger = TargetEntryTrigger()
        mask = np.zeros((19, 200), np.uint8)
        mask[:, 80:120] = 255
        self.assertTrue(trigger.observe(read_blue_target(mask, 100).overlap, "blue"))
        self.assertFalse(trigger.observe(read_blue_target(mask, 119).overlap, "blue"))
        self.assertFalse(trigger.observe(read_blue_target(mask, 100).overlap, "blue"))
        self.assertFalse(trigger.observe(read_blue_target(mask, 130).overlap, "blue"))
        self.assertTrue(trigger.observe(read_blue_target(mask, 100).overlap, "blue"))


class BlueStrategyTests(unittest.TestCase):
    def strategy(self, cls):
        config = configparser.ConfigParser()
        config.read_string(DEFAULT_CONFIG_CONTENT)
        strategy = cls(config, Rect(0, 0, 945, 532))
        strategy._start_feedback = Mock()
        strategy._time_bar_visible_from_masks = Mock(return_value=True)
        strategy._press_qte = Mock()
        if cls is AbyssMawQTEStrategy:
            strategy._blocker_detector.read = Mock(return_value=None)
        return strategy

    def run_frames(self, strategy, frames):
        strategy._grab_qte_frames = Mock(side_effect=frames)
        strategy._sleep_loop = Mock(side_effect=[None] * (len(frames) - 1) + [RunStopped("done")])
        with self.assertRaises(RunStopped):
            strategy.play_qte(Mock())
        return strategy._press_qte.call_args_list

    def test_two_strategies_reject_old_dilation_halo_in_both_directions(self):
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            for x in (72, 78, 79, 120, 121, 126):
                strategy = self.strategy(cls)
                hsv = np.zeros((19, 244, 3), np.uint8)
                hsv[:, 80:120] = (99, 200, 255)
                hsv[:, x] = (0, 0, 255)
                strategy._split_roi_and_time = lambda frame: (frame, frame)
                # 旧膨胀 + 容差会放行这些位置，必须用真实两侧边界拒绝。
                self.assertFalse(self.run_frames(strategy, [hsv] * 3), (cls.__name__, x))

    def test_real_cursor_halos_remain_pressable_with_boundary_evidence(self):
        directory = Path(__file__).parents[1] / "fixtures/qte_control"
        frames = [
            cv2.cvtColor(cv2.imread(str(directory / f"blue_only_{i}.png")), cv2.COLOR_BGR2HSV)
            for i in range(3)
        ]
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            calls = self.run_frames(self.strategy(cls), frames)
            self.assertEqual(len(calls), 1)
            details = calls[0].kwargs
            self.assertEqual(calls[0].args, ("blue_fallback",))
            self.assertEqual(details["blue_boundary_policy"], "raw_columns_inset_no_tolerance")
            self.assertTrue(
                any(a <= details["cursor_x"] < b for a, b in details["blue_safe_spans"])
            )

    def test_real_previous_exe_attempts_outside_or_with_uncertain_gap_are_rejected(self):
        directory = Path(__file__).parents[1] / "fixtures/qte_control"
        for name in ("blue_early_61247381_015_10.png", "blue_gap_61247381_018_19.png"):
            frame = cv2.cvtColor(cv2.imread(str(directory / name)), cv2.COLOR_BGR2HSV)
            for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
                self.assertFalse(self.run_frames(self.strategy(cls), [frame] * 3), (name, cls))

    def test_real_blue_overlap_survives_three_offline_scales(self):
        directory = Path(__file__).parents[1] / "fixtures/qte_control"
        raw = cv2.imread(str(directory / "u07_blue_overlap.png"))[21:40, 68:312]
        for scale in (0.925, 1, 1.5):
            frame = cv2.cvtColor(cv2.resize(raw, None, fx=scale, fy=scale), cv2.COLOR_BGR2HSV)
            strategy = self.strategy(FrostStraitQTEStrategy)
            cursor = strategy._find_cursor_x(frame)
            self.assertIsNotNone(cursor)
            reading = read_blue_target(strategy._blue_mask(frame), cursor)
            self.assertTrue(reading.overlap, (scale, reading))
