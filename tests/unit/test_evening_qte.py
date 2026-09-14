"""晚间真实泡泡破裂序列与黄条边界；所有输入均为模拟。"""

from pathlib import Path
from unittest import TestCase

import cv2
import numpy as np

from bd2_fishing.game.fishing.mechanics.bubbles import BubbleController
from bd2_fishing.game.fishing.mechanics.regions import read_mechanism_regions
from bd2_fishing.game.fishing.mechanics.yellow_aim import supported_yellow_overlap

FIXTURES = Path(__file__).parents[1] / "fixtures/qte_control/evening_20260912"


class EveningQTETests(TestCase):
    def test_burst_and_empty_frame_are_not_active_bubble_targets(self):
        for name, count in (
            ("bubble_countdown_1.png", 1),
            ("bubble_countdown_0.png", 1),
            ("seaweed_burst.png", 0),
            ("bubble_gone.png", 0),
        ):
            frame = cv2.imread(str(FIXTURES / name))[117:136, 86:330]
            regions = read_mechanism_regions(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
            self.assertEqual(len(regions.bubble_spans), count, name)

    def test_new_separate_ball_is_not_suppressed_by_consumed_previous_ball(self):
        ball = BubbleController()
        ball.observe(((40, 70),), 55, 0)
        self.assertTrue(ball.observe(((40, 70),), 55, 0.02))
        self.assertFalse(ball.observe(((100, 130),), 115, 0.04))
        self.assertTrue(ball.observe(((100, 130),), 115, 0.06))
        self.assertFalse(ball.observe(((100, 130),), 115, 0.08))

    def test_unstable_replacement_and_missing_pointer_do_not_authorize_input(self):
        ball = BubbleController()
        ball.observe(((40, 70),), 55, 0)
        ball.observe(((40, 70),), 55, 0.02)
        for i, span in enumerate(((100, 130), (160, 190), (100, 130))):
            self.assertFalse(ball.observe((span,), 115, 0.04 + i * 0.02))
        self.assertFalse(ball.observe(((100, 130),), None, 0.1))

    def test_yellow_body_rejects_outer_dilation_but_preserves_center_and_small_hole(self):
        mask = np.zeros((19, 244), np.uint8)
        mask[:, 100:130] = 255
        for x in (90, 95, 135, 140):
            self.assertIsNone(supported_yellow_overlap(mask, x, True))
        self.assertTrue(supported_yellow_overlap(mask, 114, True))
        mask[:, 110:119] = 0
        self.assertTrue(supported_yellow_overlap(mask, 114, True))
        for value in (False, None):
            self.assertIs(supported_yellow_overlap(mask, 114, value), value)
        mask[:] = 0
        mask[:, 113:115] = 255
        self.assertIsNone(supported_yellow_overlap(mask, 114, True))
