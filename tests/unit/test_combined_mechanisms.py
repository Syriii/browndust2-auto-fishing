"""真实贝壳正负图与显式合成的组合状态回放；不连接游戏。"""

from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2
import numpy as np

from bd2_fishing.game.fishing.mechanics.bubble_targets import BubbleTargets
from bd2_fishing.game.fishing.mechanics.policy import MechanismPolicy
from bd2_fishing.game.fishing.mechanics.regions import (
    GreenTarget,
    MechanismRegions,
    read_mechanism_regions,
)
from bd2_fishing.game.fishing.mechanics.shells import read_shell_spans
from bd2_fishing.game.fishing.pointer import read_pointer
from bd2_fishing.game.fishing.qte import AbyssMawQTEStrategy, FrostStraitQTEStrategy
from tests.unit.test_mechanism_policy import regions
from tests.unit.test_yellow_source_evidence import strategy

FIXTURES = Path(__file__).parents[1] / "fixtures/qte_control"


class CombinedMechanismTests(TestCase):
    def test_two_balls_are_confirmed_and_consumed_independently(self):
        pool = BubbleTargets()
        spans = ((20, 50), (80, 110))
        self.assertFalse(pool.observe(spans, 35, 0))
        self.assertTrue(pool.observe(spans, 35, 0.02))
        self.assertEqual(pool.span, (20, 50))
        self.assertFalse(pool.observe(spans, 35, 0.04))
        self.assertTrue(pool.observe(spans, 95, 0.06))
        self.assertEqual(pool.span, (80, 110))
        self.assertFalse(pool.observe(spans, 95, 0.08))

    def test_ball_identity_survives_order_changes_and_temporary_occlusion(self):
        pool = BubbleTargets()
        spans = ((20, 50), (80, 110))
        pool.observe(spans, 35, 0)
        self.assertTrue(pool.observe(tuple(reversed(spans)), 35, 0.02))
        pool.observe((), None, 0.04, uncertain=True)
        self.assertFalse(pool.observe(spans, 35, 0.06))
        self.assertFalse(pool.observe(spans, 35, 0.08))

    def test_ambiguous_excess_targets_and_blocked_cursor_never_press(self):
        pool = BubbleTargets()
        for spans in (((20, 50), (30, 60)), tuple((i * 20, i * 20 + 10) for i in range(5))):
            for t in (0, 0.02, 0.04):
                self.assertFalse(pool.observe(spans, 35, t))
        for t in (0.1, 0.12, 0.14):
            self.assertFalse(pool.observe(((20, 50),), 35, t, blocked=True))

    def test_disjoint_ball_not_blocked_by_unmarked_green_entry(self):
        machine = MechanismPolicy()
        frame = regions(green=GreenTarget(80, 115), bubble=((20, 50),))
        self.assertEqual(machine.observe(frame, 5, 0).action, "wait")
        self.assertEqual(machine.observe(frame, 35, 0.02).action, "press")
        self.assertFalse(machine.green.held)
        self.assertNotEqual(machine.observe(frame, 35, 0.04).action, "press")

    def test_held_green_keeps_exclusive_input_even_with_a_disjoint_ball(self):
        machine = MechanismPolicy()
        frame = regions(green=GreenTarget(20, 65, (20, 35)), bubble=((80, 110),))
        machine.observe(frame, 15, 0)
        self.assertEqual(machine.observe(frame, 30, 0.02).action, "down")
        self.assertEqual(machine.observe(frame, 95, 0.04).action, "up")
        self.assertFalse(machine.bubble.consumed)

    def test_real_shell_pair_blocks_both_spans_at_multiple_sizes(self):
        image = cv2.imread(str(FIXTURES / "evening_20260912/shells_over_bubble.png"))[
            117:136, 86:330
        ]
        for scale in (0.925, 1, 1.5, 2):
            hsv = cv2.cvtColor(cv2.resize(image, None, fx=scale, fy=scale), cv2.COLOR_BGR2HSV)
            found = read_mechanism_regions(hsv)
            self.assertEqual(len(found.shell_spans), 2)
            for left, right in found.shell_spans:
                self.assertTrue(found.blocked[left:right].all())
                self.assertFalse(found.ordinary_pixels(hsv)[:, left:right].any())

    def test_bubble_burst_and_ordinary_bar_are_not_shells(self):
        for path in (FIXTURES / "evening_20260912").glob("*.png"):
            if path.name.startswith("shell"):
                continue
            frame = cv2.imread(str(path))[117:136, 86:330]
            self.assertFalse(read_shell_spans(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)), path.name)

    def test_real_later_shell_frames_are_detected_without_using_template_source(self):
        for path in (FIXTURES / "evening_20260912").glob("shell_holdout_*.png"):
            frame = cv2.imread(str(path))[117:136, 86:330]
            self.assertEqual(len(read_shell_spans(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))), 2)

    def test_blocker_never_projects_cursor_onto_a_nearby_yellow_target(self):
        s = strategy(AbyssMawQTEStrategy)
        s._blocker_detector.read_all = Mock(return_value=((90, 0, 20, 19),))
        hsv = np.zeros((19, 244, 3), np.uint8)
        hsv[:, 78:90] = (25, 255, 255)
        for _ in range(3):
            s._track_targets(hsv, 95, read_mechanism_regions(hsv))
        s._press_qte.assert_not_called()

    def test_only_blue_with_shells_uses_visible_blue_and_not_shell_texture(self):
        raw = cv2.imread(str(FIXTURES / "evening_20260912/shells_over_bubble.png"))[117:136, 86:330]
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            for x in (45, 155):
                # 真实贝壳贴入合成蓝条，明确是组合边界测试，不是游戏成功样本。
                hsv = np.zeros((19, 244, 3), np.uint8)
                hsv[:, 15:180] = (99, 200, 255)
                shell = cv2.cvtColor(raw, cv2.COLOR_BGR2HSV)
                hsv[:, 30:65] = shell[:, 30:65]
                hsv[:, 97:132] = shell[:, 97:132]
                s = strategy(cls)
                if cls is AbyssMawQTEStrategy:
                    s._blocker_detector.read_all = Mock(return_value=())
                for _ in range(3):
                    s._track_targets(hsv, x, read_mechanism_regions(hsv))
                if x == 45:
                    s._press_qte.assert_not_called()
                else:
                    s._press_qte.assert_called_once()
                    self.assertEqual(s._press_qte.call_args.kwargs["target"], "blue")

    def test_bubble_and_clone_candidates_use_bright_pointer_only(self):
        hsv = np.zeros((19, 244, 3), np.uint8)
        hsv[:, 35] = (0, 0, 165)
        hsv[:, 95] = (0, 0, 255)
        cursor = read_pointer(hsv).x
        self.assertEqual(cursor, 95)
        pool = BubbleTargets()
        pool.observe(((20, 50), (80, 110)), cursor, 0)
        self.assertTrue(pool.observe(((20, 50), (80, 110)), cursor, 0.02))
        self.assertEqual(pool.span, (80, 110))

    def test_shell_clone_and_blue_only_are_arbitrated_together(self):
        raw = cv2.imread(str(FIXTURES / "evening_20260912/shells_over_bubble.png"))[117:136, 86:330]
        shells = cv2.cvtColor(raw, cv2.COLOR_BGR2HSV)
        hsv = np.zeros_like(shells)
        hsv[:, 30:65] = shells[:, 30:65]
        hsv[:, 97:132] = shells[:, 97:132]
        hsv[:, 135:190] = (99, 200, 255)
        hsv[:, 155] = (0, 0, 255)
        hsv[:, 225] = (0, 0, 165)
        cursor = read_pointer(hsv).x
        self.assertEqual(cursor, 155)
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            s = strategy(cls)
            if cls is AbyssMawQTEStrategy:
                s._blocker_detector.read_all = Mock(return_value=())
            for i in range(3):
                with patch("bd2_fishing.game.fishing.qte.time.monotonic", return_value=i * 0.02):
                    handled, found = s._mechanism_step(hsv, cursor)
                    self.assertEqual(len(found.shell_spans), 2)
                    if not handled:
                        s._track_targets(hsv, cursor, found)
            s._press_qte.assert_called_once()
            self.assertEqual(s._press_qte.call_args.kwargs["target"], "blue")

    def test_combination_snapshots_are_deduplicated_and_bounded(self):
        s = strategy()
        with patch.object(s, "_cache_mechanism_frame") as cache:
            for i in range(32):
                mask = np.zeros(244, bool)
                frame = MechanismRegions(
                    bool(i & 1),
                    None,
                    mask,
                    ((10, 20),) if i & 2 else (),
                    ((30, 40),) if i & 4 else (),
                    ((50, 80),) if i & 8 else (),
                    ((90, 110),) if i & 16 else (),
                )
                s._cache_first_mechanisms(frame)
                s._cache_first_mechanisms(frame)
        names = [
            c.args[0]
            for c in cache.call_args_list
            if c.args[0].startswith("mechanism_combination_")
        ]
        self.assertEqual(len(names), 8)
        self.assertEqual(len(set(names)), 8)
