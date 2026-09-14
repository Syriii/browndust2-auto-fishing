"""计时特效与泡泡残影连续性；原图与模拟时间分开验证，不操作游戏。"""

import json
from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2
import numpy as np

from bd2_fishing.game.fishing import qte
from bd2_fishing.game.fishing.mechanics.policy import MechanismPolicy
from bd2_fishing.game.fishing.mechanics.regions import (
    GreenTarget,
    MechanismRegions,
    read_mechanism_regions,
)
from bd2_fishing.game.fishing.presence import QTEPresence
from bd2_fishing.runtime import control
from tests.unit.test_yellow_source_evidence import strategy

FIXTURES = Path(__file__).parents[1] / "fixtures/qte_control/continuity_20260913"


class ContinuityTests(TestCase):
    def test_grace_needs_recent_timer_and_current_pointer_and_target(self):
        p = QTEPresence()
        self.assertFalse(p.observe(False, True, 30, 0))
        self.assertTrue(p.observe(True, False, None, 1))
        self.assertTrue(p.observe(False, True, 30, 1.02))
        for i in range(2, 20):
            self.assertEqual(p.observe(False, True, 30, 1 + i * 0.02), i * 0.02 <= 0.35)
        self.assertTrue(p.observe(True, True, 30, 2))
        self.assertFalse(p.observe(False, True, None, 2.02))
        self.assertFalse(p.observe(False, True, 30, 2.04))
        self.assertTrue(p.observe(False, True, 30, 2.06))
        self.assertFalse(p.observe(False, False, 30, 2.08))
        self.assertFalse(p.observe(False, True, 30, 2.3))

    def test_missing_frame_and_long_gap_do_not_extend_grace(self):
        p = QTEPresence()
        p.observe(True, True, 30, 0)
        p.invalidate()
        self.assertFalse(p.observe(False, True, 30, 0.02))
        self.assertFalse(p.observe(False, True, 30, 0.2))
        self.assertFalse(p.observe(False, True, 30, 0.4))

    def test_real_effect_frame_reaches_blue_policy_then_stops_after_grace(self):
        s = strategy()
        s._start_feedback = Mock()
        s._stop_feedback = Mock()
        raw = cv2.imread(str(FIXTURES / "timer-frame_03.png"))[96:138, 18:330]
        hsv = cv2.cvtColor(raw, cv2.COLOR_BGR2HSV)
        timer, target = s._split_roi_and_time(hsv)
        self.assertFalse(s._time_bar_visible(timer))
        self.assertIsNotNone(s._find_cursor_x(target))
        # 图像保持真实；模拟 20 ms 控制采样及前一帧已确认计时颜色。
        s._grab_qte_frames = Mock(return_value=hsv)
        s._time_bar_visible_from_masks = Mock(side_effect=[True] + [False] * 30)
        s._on_bar_disappeared = Mock(return_value=False)
        s._cache_mechanism_frame = Mock()
        clock = [1.0]

        def sleep():
            clock[0] += 0.02
            if clock[0] >= 1.5:
                raise control.RunStopped("bounded replay")

        s._sleep_loop = sleep
        with patch.object(qte.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(control.RunStopped):
                s.play_qte(Mock())
        s._press_qte.assert_called_once()
        self.assertEqual(s._press_qte.call_args.kwargs["target"], "blue")
        self.assertTrue(s._on_bar_disappeared.called)

    def test_real_bubble_to_seaweed_sequences_only_block_local_area(self):
        policy = MechanismPolicy()
        changed = 0
        for entry in json.loads((FIXTURES / "manifest.json").read_text(encoding="utf8")):
            if entry["file"].startswith("timer"):
                continue
            frame = cv2.imread(str(FIXTURES / entry["file"]))[117:136, 86:330]
            regions = read_mechanism_regions(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
            decision = policy.observe(regions, 200, entry["stamp"])
            if regions.green_present:
                changed += 1
                self.assertEqual(decision.action, "normal")
                self.assertFalse(policy.regions.green_present)
                self.assertTrue(policy.regions.blocked.any())
                self.assertFalse(policy.regions.blocked[200])
        self.assertEqual(changed, 5)

    def test_unknown_green_expiry_and_active_hold_keep_green_protection(self):
        base = MechanismRegions(False, None, np.zeros(244, bool), (), (), ((40, 70),))
        remnant = replace(
            base,
            bubble_spans=(),
            green_present=True,
            green=GreenTarget(40, 65),
            green_spans=((40, 65),),
        )
        p = MechanismPolicy()
        self.assertEqual(p.observe(remnant, 100, 0).action, "normal")
        self.assertTrue(p.regions.green_present)
        self.assertFalse(p.regions.bubble_remnant_spans)
        self.assertTrue(p.regions.blocked[50])
        p.observe(base, 100, 1)
        p.observe(base, 100, 1.02)
        p.observe(remnant, 100, 1.04)
        self.assertTrue(p.regions.bubble_remnant_spans)
        self.assertEqual(p.observe(remnant, 100, 2).action, "normal")
        self.assertTrue(p.regions.green_present)
        self.assertFalse(p.regions.bubble_remnant_spans)
        self.assertEqual(p.observe(remnant, 50, 2.02).action, "wait")
        p.observe(base, 100, 3)
        p.observe(base, 100, 3.02)
        p.green.held = True
        p.observe(remnant, 100, 3.04)
        self.assertTrue(p.regions.green_present)

    def test_remnant_and_another_green_mechanism_keep_hold_priority(self):
        base = MechanismRegions(False, None, np.zeros(244, bool), (), (), ((40, 70),))
        p = MechanismPolicy()
        p.observe(base, 150, 0)
        p.observe(base, 150, 0.02)
        mixed = replace(
            base,
            bubble_spans=(),
            green_present=True,
            green_spans=((40, 65), (100, 170)),
            green=GreenTarget(100, 170),
        )
        self.assertEqual(p.observe(mixed, 150, 0.04).action, "wait")
        self.assertTrue(p.regions.green_present)
        self.assertEqual(p.regions.green_spans, ((100, 170),))
        self.assertTrue(p.regions.blocked[50])

    def test_remnant_allows_yellow_outside_but_not_inside_its_area(self):
        for cls in (qte.FrostStraitQTEStrategy, qte.AbyssMawQTEStrategy):
            for cursor in (50, 110):
                s = strategy(cls)
                base = MechanismRegions(False, None, np.zeros(244, bool), (), (), ((40, 70),))
                s._mechanism_policy.observe(base, 150, 0)
                s._mechanism_policy.observe(base, 150, 0.02)
                remnant = replace(
                    base,
                    bubble_spans=(),
                    green_present=True,
                    green_spans=((40, 65),),
                    green=GreenTarget(40, 65),
                )
                s._mechanism_policy.observe(remnant, cursor, 0.04)
                # 合成目标/光标位置只验证组合仲裁，不当作真实游戏命中。
                hsv = np.zeros((19, 244, 3), np.uint8)
                hsv[:, 40:125] = (25, 255, 255)
                s._track_targets(hsv, cursor, s._mechanism_policy.regions)
                self.assertEqual(s._press_qte.call_count, 1 if cursor == 110 else 0)

    def test_single_bubble_frame_and_unrelated_green_are_not_relabelled_as_remnants(self):
        base = MechanismRegions(False, None, np.zeros(244, bool), (), (), ((40, 70),))
        p = MechanismPolicy()
        p.observe(base, 100, 0)
        green = replace(base, bubble_spans=(), green_present=True, green_spans=((40, 65),))
        self.assertEqual(p.observe(green, 100, 0.02).action, "normal")
        self.assertTrue(p.regions.green_present)
        self.assertFalse(p.regions.bubble_remnant_spans)
        self.assertEqual(p.observe(green, 50, 0.04).action, "wait")
        p.observe(base, 100, 1)
        p.observe(base, 100, 1.02)
        unrelated = replace(green, green_spans=((90, 130),))
        self.assertEqual(p.observe(unrelated, 150, 1.04).action, "normal")
        self.assertTrue(p.regions.green_present)
        self.assertFalse(p.regions.bubble_remnant_spans)
        self.assertEqual(p.observe(unrelated, 100, 1.06).action, "wait")
