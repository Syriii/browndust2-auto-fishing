"""中心偏好只延后安全机会：真实前序图回放与可控运动边界。"""

import hashlib
import json
from unittest import TestCase
from unittest.mock import patch

import cv2
import numpy as np

from bd2_fishing.game.fishing.mechanics.policy import TargetPolicy
from bd2_fishing.game.fishing.mechanics.regions import read_mechanism_regions
from bd2_fishing.game.fishing.mechanics.yellow_aim import YellowAim, visible_yellow_span
from bd2_fishing.game.fishing.qte import AbyssMawQTEStrategy, FrostStraitQTEStrategy
from tests.unit.test_yellow_source_evidence import FIXTURES, read_frame, strategy


def target(left=100, right=130):
    mask = np.zeros((19, 244), np.uint8)
    mask[:, left:right] = 255
    return mask


def observe(aim, cursor, now, *, mask=None, overlap=True, forbidden=None, loop=0.02):
    return aim.observe(
        target() if mask is None else mask,
        cursor,
        now,
        overlap=overlap,
        forbidden=np.zeros(244, bool) if forbidden is None else forbidden,
        loop_seconds=loop,
    )


class YellowAimTests(TestCase):
    def test_both_directions_defer_edge_then_keep_near_center(self):
        for path in ((84, 89, 94, 99, 104, 109, 114), (145, 140, 135, 130, 125, 120, 115)):
            with self.subTest(path=path):
                aim = YellowAim()
                readings = [observe(aim, x, 1 + i * 0.02) for i, x in enumerate(path)]
                self.assertIsNone(readings[2].overlap)
                self.assertEqual(readings[2].reason, "prefer_center")
                self.assertTrue(readings[-1].overlap)
                self.assertLessEqual(abs(path[-1] - readings[-1].center), 1)

    def test_fast_motion_and_long_sampling_cycle_do_not_skip_current_opportunity(self):
        for positions, loop in (((44, 69, 94), 0.02), ((84, 89, 94), 0.1)):
            aim = YellowAim()
            for i, x in enumerate(positions):
                result = observe(aim, x, 1 + i * 0.02, loop=loop)
            self.assertTrue(result.overlap)

    def test_reversal_stall_gap_and_reset_do_not_continue_deferring(self):
        for last_x, last_t in ((89, 1.06), (94, 1.06), (99, 1.3)):
            aim = YellowAim()
            for i, x in enumerate((84, 89, 94)):
                result = observe(aim, x, 1 + i * 0.02)
            self.assertIsNone(result.overlap)
            self.assertTrue(observe(aim, last_x, last_t).overlap)
        aim.reset()
        self.assertTrue(observe(aim, 94, 2).overlap)

    def test_mechanism_near_target_disables_deferral_but_distant_one_does_not(self):
        for start, expected in ((98, True), (170, None)):
            aim = YellowAim()
            blocked = np.zeros(244, bool)
            blocked[start : start + 3] = True
            for i, x in enumerate((84, 89, 94)):
                result = observe(aim, x, 1 + i * 0.02, forbidden=blocked)
            self.assertIs(result.overlap, expected)

    def test_narrow_fragment_or_moving_target_keeps_existing_opportunity(self):
        for mask in (target(100, 108), target(160, 190), np.zeros((19, 244), np.uint8)):
            aim = YellowAim()
            observe(aim, 84, 1)
            observe(aim, 89, 1.02)
            self.assertTrue(observe(aim, 94, 1.04, mask=mask).overlap)

    def test_never_creates_permission_or_rearms_during_deferral(self):
        policy = TargetPolicy()
        self.assertEqual(policy.observe(yellow_present=True, yellow_overlap=True), "yellow")
        for i, x in enumerate((84, 89, 94, 99, 104, 109, 114)):
            reading = observe(policy.yellow_aim, x, 1 + i * 0.02)
            self.assertIsNone(policy.observe(yellow_present=True, yellow_overlap=reading.overlap))
        for overlap in (False, None):
            self.assertIs(observe(policy.yellow_aim, 115, 2, overlap=overlap).overlap, overlap)

    def test_invalidation_clears_motion_without_rearming_press(self):
        policy = TargetPolicy()
        policy.observe(yellow_present=True, yellow_overlap=True)
        observe(policy.yellow_aim, 84, 1)
        observe(policy.yellow_aim, 89, 1.02)
        policy.invalidate()
        reading = observe(policy.yellow_aim, 94, 1.04)
        self.assertTrue(reading.overlap)
        self.assertIsNone(policy.observe(yellow_present=True, yellow_overlap=reading.overlap))

    def test_cursor_hole_preserves_endpoints_without_growing_outer_boundary(self):
        mask = target()
        mask[:, 110:119] = 0
        self.assertEqual(visible_yellow_span(mask, 114), (100, 130))
        self.assertEqual(visible_yellow_span(mask, 94), (100, 110))
        mask[:, 109:122] = 0
        self.assertNotEqual(visible_yellow_span(mask, 114), (100, 130))

    def test_resolution_change_invalidates_trajectory(self):
        aim = YellowAim()
        observe(aim, 84, 1)
        observe(aim, 89, 1.02)
        large = cv2.resize(target(), (488, 38), interpolation=cv2.INTER_NEAREST)
        self.assertTrue(observe(aim, 188, 1.04, mask=large, forbidden=np.zeros(488, bool)).overlap)

    def test_both_strategies_wait_then_press_once_without_extra_input(self):
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            controller = strategy(cls)
            for i, cursor in enumerate((84, 89, 94, 99, 104, 109, 114, 114)):
                hsv = np.zeros((19, 244, 3), np.uint8)
                hsv[:, 100:130] = (25, 255, 255)
                hsv[:, cursor] = (0, 0, 255)
                with patch(
                    "bd2_fishing.game.fishing.qte.time.monotonic", return_value=1 + i * 0.02
                ):
                    controller._track_targets(hsv, cursor, read_mechanism_regions(hsv))
                if i <= 4:
                    controller._press_qte.assert_not_called()
            controller._press_qte.assert_called_once()
            self.assertLessEqual(abs(controller._press_qte.call_args.kwargs["cursor_x"] - 114.5), 6)
            self.assertIn("yellow_aim", controller._press_qte.call_args.kwargs)

    def test_real_motion_replay_defers_m10_m15_but_not_unstable_m03(self):
        # 独立观察器的前序帧用于轨迹边界回放；不是连续控制帧或新命中结果。
        for record in json.loads((FIXTURES / "motion.json").read_text("utf-8")):
            controller = strategy()
            for frame in record["frames"]:
                path = FIXTURES / frame["file"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), frame["sha256"])
                y1, y2, x1, x2 = frame["crop"]
                hsv = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2HSV)[y1:y2, x1:x2]
                cursor = controller._find_cursor_x(hsv)
                with patch(
                    "bd2_fishing.game.fishing.qte.time.monotonic", return_value=frame["time"]
                ):
                    controller._track_targets(hsv, cursor, read_mechanism_regions(hsv))
            controller._press_qte.assert_not_called()
            hsv = read_frame(controller, record["id"])
            cursor = controller._find_cursor_x(hsv)
            with patch(
                "bd2_fishing.game.fishing.qte.time.monotonic", return_value=record["decision_time"]
            ):
                controller._track_targets(hsv, cursor, read_mechanism_regions(hsv))
            if record["id"] == "M03":
                controller._press_qte.assert_called_once()
            else:
                controller._press_qte.assert_not_called()
                self.assertEqual(controller._yellow_aim_decision.reason, "prefer_center")
