from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2
import numpy as np

from bd2_fishing.app.fishing_task import QTE_STRATEGIES_MAP
from bd2_fishing.game.fishing.mechanics.blockers import active_range_for_blockers
from bd2_fishing.game.fishing.mechanics.regions import GreenTarget, read_mechanism_regions
from bd2_fishing.game.fishing.qte import AbyssMawQTEStrategy
from tests.unit.test_yellow_geometry import read_frame
from tests.unit.test_yellow_source_evidence import strategy


class MultipleWallTests(TestCase):
    def test_compressed_pointer_and_real_yellow_texture_are_not_walls(self):
        controller = strategy(AbyssMawQTEStrategy)
        for filename in ("Y05.png", "Y39.png"):
            hsv = read_frame(controller, filename)
            self.assertEqual(
                controller._blocker_detector.read_all(hsv, controller._cursor_mask(hsv)), ()
            )
        original = cv2.imread(
            str(Path(__file__).parents[1] / "fixtures/qte_control/guide_20260914/wall_gamekee.webp")
        )
        controller = strategy(AbyssMawQTEStrategy, width=1920, height=1080)
        full = cv2.cvtColor(original, cv2.COLOR_BGR2HSV)
        self.assertEqual(
            controller._blocker_detector.read_all(full, controller._cursor_mask(full)), ()
        )
        # 完整攻略小图不是控制 ROI。条体裁剪保留独立来源的真实墙体。
        bar = full[32:71]
        self.assertEqual(
            controller._blocker_detector.read_all(bar, controller._cursor_mask(bar)),
            ((60, 0, 9, 39),),
        )

    def test_every_registered_location_uses_wall_bounds_and_reuses_same_frame(self):
        for location, cls in QTE_STRATEGIES_MAP.items():
            with self.subTest(location=location):
                controller = strategy(cls)
                detector = controller._blocker_detector.read_all = Mock(
                    return_value=((20, 0, 10, 19), (160, 0, 10, 19))
                )
                hsv = np.zeros((19, 244, 3), np.uint8)
                hsv[:, 50:120] = (99, 200, 255)
                hsv[:, 180:230] = (25, 255, 255)
                for _ in range(3):
                    handled, regions = controller._mechanism_step(hsv, 80)
                    self.assertFalse(handled)
                    controller._track_targets(hsv, 80, regions)
                self.assertEqual(detector.call_count, 3)
                controller._press_qte.assert_called_once()
                self.assertEqual(controller._press_qte.call_args.kwargs["target"], "blue")
                self.assertEqual(controller._press_qte.call_args.kwargs["active_range"], (30, 159))

    def test_wall_overlap_blocks_bubble_input_at_every_location(self):
        hsv = np.zeros((19, 244, 3), np.uint8)
        bubble = replace(read_mechanism_regions(hsv), bubble_spans=((70, 115),))
        for location, cls in QTE_STRATEGIES_MAP.items():
            with self.subTest(location=location):
                controller = strategy(cls)
                controller._blocker_detector.read_all = Mock(return_value=((80, 0, 20, 19),))
                with patch(
                    "bd2_fishing.game.fishing.qte.read_mechanism_regions", return_value=bubble
                ):
                    for _ in range(3):
                        controller._mechanism_step(hsv, 90)
                controller._press_qte.assert_not_called()
                self.assertFalse(bubble.blocked.any(), "原始区域不可被墙合并原地改写")

    def test_wall_overlap_releases_existing_green_hold_at_every_location(self):
        hsv = np.zeros((19, 244, 3), np.uint8)
        target = GreenTarget(20, 120, (20, 40))
        green = replace(
            read_mechanism_regions(hsv), green_present=True, green=target, green_spans=((20, 120),)
        )
        for location, cls in QTE_STRATEGIES_MAP.items():
            with self.subTest(location=location):
                controller = strategy(cls)
                machine = controller._mechanism_policy.green
                machine.observe(target, 15, 0, present=True)
                self.assertEqual(machine.observe(target, 30, 0.02, present=True).action, "down")
                controller._blocker_detector.read_all = Mock(return_value=((30, 0, 15, 19),))
                controller._release_green_key = Mock()
                with (
                    patch(
                        "bd2_fishing.game.fishing.qte.read_mechanism_regions", return_value=green
                    ),
                    patch("bd2_fishing.game.fishing.qte.time.monotonic", return_value=0.04),
                    self.assertRaisesRegex(RuntimeError, "green_tracking_lost"),
                ):
                    controller._mechanism_step(hsv, 35)
                controller._release_green_key.assert_called_once()
                controller._press_qte.assert_not_called()

    def test_order_does_not_change_reachable_interval_and_cursor_is_never_projected(self):
        walls = ((20, 0, 10, 30), (80, 0, 10, 30))
        for order in (walls, tuple(reversed(walls))):
            self.assertEqual(active_range_for_blockers(order, 50, 120), (30, 79))
            self.assertEqual(active_range_for_blockers(order, 10, 120), (0, 19))
            self.assertEqual(active_range_for_blockers(order, 100, 120), (90, 119))
            for cursor in (20, 29, 80, 89, None, -1, 120):
                self.assertIsNone(active_range_for_blockers(order, cursor, 120))

    def test_real_wall_is_distinct_from_bright_pointer(self):
        frame = cv2.imread(
            str(Path(__file__).parents[1] / "fixtures/qte_control/guide_20260914/wall.png")
        )
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        controller = strategy(AbyssMawQTEStrategy, width=1920, height=1080)
        found = controller._blocker_detector.read_all(hsv, controller._cursor_mask(hsv))
        self.assertEqual(found, ((408, 5, 27, 110),))
        self.assertEqual(controller._find_cursor_x(hsv), 379)
        # 从同帧真指针所在范围取负例，保留原始压缩纹理，不能误认成墙。
        pointer_only = hsv[:, 345:398]
        self.assertFalse(
            controller._blocker_detector.read_all(
                pointer_only, controller._cursor_mask(pointer_only)
            )
        )

    def test_all_synthetic_walls_are_retained(self):
        controller = strategy(AbyssMawQTEStrategy, width=1920, height=1080)
        hsv = np.zeros((100, 320, 3), np.uint8)
        hsv[10:90, 30:42] = (30, 35, 250)
        hsv[10:90, 240:252] = (30, 35, 250)
        found = controller._blocker_detector.read_all(hsv, np.zeros(hsv.shape[:2], np.uint8))
        self.assertEqual(len(found), 2)
        self.assertLess(found[0][0], found[1][0])

    def test_unreachable_yellow_does_not_prevent_safe_blue_between_walls(self):
        controller = strategy(AbyssMawQTEStrategy)
        controller._blocker_detector.read_all = Mock(
            return_value=((20, 0, 10, 19), (160, 0, 10, 19))
        )
        hsv = np.zeros((19, 244, 3), np.uint8)
        hsv[:, 50:120] = (99, 200, 255)
        hsv[:, 180:230] = (25, 255, 255)
        for _ in range(3):
            controller._track_targets(hsv, 80, read_mechanism_regions(hsv))
        controller._press_qte.assert_called_once()
        self.assertEqual(controller._press_qte.call_args.kwargs["active_range"], (30, 159))
        self.assertEqual(controller._press_qte.call_args.kwargs["target"], "blue")
