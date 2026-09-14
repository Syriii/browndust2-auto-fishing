"""普通 QTE 真光标光晕的实体孔洞回归，所有输入均为模拟。"""

from pathlib import Path
from unittest import TestCase

import cv2
import numpy as np

from bd2_fishing.game.fishing.mechanics.regions import read_mechanism_regions
from bd2_fishing.game.fishing.mechanics.yellow_aim import supported_yellow_overlap
from bd2_fishing.game.fishing.qte import AbyssMawQTEStrategy, FrostStraitQTEStrategy
from tests.unit.test_yellow_source_evidence import strategy


class OrdinaryYellowGlowTests(TestCase):
    def test_actual_plain_yellow_cursor_glow_permits_one_press(self):
        path = (
            Path(__file__).parents[1]
            / "fixtures/qte_control/ordinary_20260913/yellow_cursor_glow.png"
        )
        frame = cv2.imread(str(path))[96:138, 18:330]
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            controller = strategy(cls)
            _, hsv = controller._split_roi_and_time(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
            cursor = controller._find_cursor_x(hsv)
            self.assertEqual(cursor, 106)
            regions = read_mechanism_regions(hsv)
            self.assertFalse(regions.green_present or regions.blocked.any() or regions.bubble_spans)
            for _ in range(3):
                controller._track_targets(hsv, cursor, regions)
            controller._press_qte.assert_called_once()
            self.assertEqual(controller._press_qte.call_args.kwargs["target"], "yellow")

    def test_scaled_internal_glow_needs_both_sides_and_no_obstruction(self):
        for scale in (1, 2):
            mask = np.zeros((19 * scale, 244 * scale), np.uint8)
            mask[:, 93 * scale : 100 * scale] = 255
            mask[:, 113 * scale : 117 * scale] = 255
            cursor = 106 * scale
            self.assertTrue(supported_yellow_overlap(mask, cursor, True))
            forbidden = np.zeros(mask.shape[1], bool)
            forbidden[108 * scale : 110 * scale] = True
            self.assertIsNone(supported_yellow_overlap(mask, cursor, True, forbidden=forbidden))
            mask[:, : 100 * scale] = 0
            self.assertIsNone(supported_yellow_overlap(mask, cursor, True))

    def test_wide_gap_or_isolated_pixels_never_reconstruct_target(self):
        mask = np.zeros((19, 244), np.uint8)
        mask[:, 80:90] = 255
        mask[:, 115:125] = 255
        self.assertIsNone(supported_yellow_overlap(mask, 103, True))
        mask[:] = 0
        mask[:, 98] = 255
        mask[:, 113] = 255
        self.assertIsNone(supported_yellow_overlap(mask, 106, True))
