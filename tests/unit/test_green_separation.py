"""真实泡泡过渡帧与明确合成的光标移动/蓝区组合；不发送游戏输入。"""

from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import cv2
import numpy as np

from bd2_fishing.game.fishing.mechanics.policy import MechanismPolicy
from bd2_fishing.game.fishing.mechanics.regions import GreenTarget, read_mechanism_regions
from bd2_fishing.game.fishing.qte import AbyssMawQTEStrategy, FrostStraitQTEStrategy
from tests.unit.test_mechanism_policy import regions
from tests.unit.test_yellow_source_evidence import strategy

FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures/qte_control/green_separation_20260914/bubble_transition.png"
)


def real_frame(s):
    raw = cv2.imread(str(FIXTURE))
    return s._split_roi_and_time(cv2.cvtColor(raw, cv2.COLOR_BGR2HSV))[1]


def step(s, hsv, cursor, stamp):
    with patch("bd2_fishing.game.fishing.qte.time.monotonic", return_value=stamp):
        handled, found = s._mechanism_step(hsv, cursor)
        if not handled:
            s._track_targets(hsv, cursor, found)
    return handled, found


class GreenSeparationTests(TestCase):
    def test_real_transition_resumes_detection_but_does_not_press_outside_yellow(self):
        s = strategy()
        hsv = real_frame(s)
        cursor = s._find_cursor_x(hsv)
        self.assertEqual(cursor, 146)
        handled, found = step(s, hsv, cursor, 0)
        self.assertFalse(handled)
        self.assertTrue(found.green_present)
        self.assertTrue(found.blocked[31:78].all())
        self.assertFalse(found.blocked[cursor])
        self.assertEqual(s._yellow_aim_decision.span, (154, 169))
        s._press_qte.assert_not_called()

    def test_simulated_cursor_enters_real_separate_yellow_once_for_both_strategies(self):
        # 原帧背景不动，仅模拟下一时刻光标位置；不是录制到的真实轨迹。
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            s = strategy(cls)
            hsv = real_frame(s)
            for cursor, stamp in ((146, 0), (160, 0.02), (162, 0.04)):
                step(s, hsv, cursor, stamp)
            s._press_qte.assert_called_once()
            self.assertEqual(s._press_qte.call_args.kwargs["target"], "yellow")

    def test_synthetic_blue_only_keeps_two_frame_confirmation_and_dedup(self):
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            s = strategy(cls)
            hsv = real_frame(s)
            hsv[:, 145:175] = (99, 200, 255)  # 显式合成：把原黄条替换为蓝区。
            step(s, hsv, 160, 0)
            s._press_qte.assert_not_called()
            step(s, hsv, 160, 0.02)
            step(s, hsv, 160, 0.04)
            s._press_qte.assert_called_once()
            self.assertEqual(s._press_qte.call_args.kwargs["target"], "blue")

    def test_green_occlusion_and_missing_frame_do_not_rearm_a_consumed_target(self):
        s = strategy()
        hsv = real_frame(s)
        step(s, hsv, 160, 0)
        s._press_qte.assert_called_once()
        self.assertTrue(step(s, hsv, 50, 0.02)[0])
        s._mechanism_policy.invalidate_observation()
        step(s, hsv, 160, 0.04)
        s._press_qte.assert_called_once()
        # 真正重新观测到普通目标外，才可解锁下次入区。
        step(s, hsv, 200, 0.06)
        step(s, hsv, 160, 0.08)
        self.assertEqual(s._press_qte.call_count, 2)

    def test_unknown_location_and_green_hull_holes_remain_blocked(self):
        base = regions(green=GreenTarget(20, 90))
        for frame, cursor in (
            (replace(base, green=None), 110),
            (replace(base, green=None, green_spans=((20, 30), (80, 90))), 50),
            (replace(base, green_spans=((20, 90),)), 91),
        ):
            machine = MechanismPolicy()
            self.assertEqual(machine.observe(frame, cursor, 0).action, "wait")
            self.assertFalse(machine.targets.trigger.target)

    def test_active_hold_and_release_still_exclude_ordinary_input(self):
        frame = replace(regions(green=GreenTarget(20, 90, (20, 35))), green_spans=((20, 90),))
        machine = MechanismPolicy()
        machine.observe(frame, 15, 0)
        self.assertEqual(machine.observe(frame, 30, 0.02).action, "down")
        self.assertEqual(machine.observe(frame, 100, 0.04).action, "up")

    def test_scaled_exclusion_keeps_other_obstacles_and_does_not_mutate_source(self):
        base = read_mechanism_regions(real_frame(strategy()))
        for scale in (1, 1.5, 2):
            # 已识别跨度按比例缩放，独立验证几何避让，不混入HSV插值误差。
            mask = np.zeros(round(len(base.blocked) * scale), dtype=bool)
            mask[round(155 * scale) : round(170 * scale)] = True
            frame = replace(
                base,
                blocked=mask,
                green_spans=tuple(
                    (round(a * scale), round(b * scale)) for a, b in base.green_spans
                ),
            )
            before = mask.copy()
            ordinary = frame.with_green_exclusion()
            self.assertTrue(np.array_equal(frame.blocked, before))
            self.assertTrue(ordinary.blocked[round(160 * scale)])
            self.assertTrue(ordinary.blocked[round(50 * scale)])
            self.assertFalse(ordinary.blocked[round(100 * scale)])
