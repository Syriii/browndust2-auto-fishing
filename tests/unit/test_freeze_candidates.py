from pathlib import Path
from unittest import TestCase

import cv2
import numpy as np

from bd2_fishing.game.fishing.mechanics.freeze_candidates import read_freeze_candidate

ROOT = Path(__file__).parents[1] / "fixtures/qte_control/freeze_20260914"


def read(path):
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2HSV)


class FreezeCandidateTests(TestCase):
    def test_independent_guide_ice_three_at_several_sizes(self):
        bgr = cv2.imread(str(ROOT / "ice.png"))
        for scale in (0.5, 0.75, 1, 1.5, 2):
            resized = cv2.resize(bgr, None, fx=scale, fy=scale)
            candidate = read_freeze_candidate(cv2.cvtColor(resized, cv2.COLOR_BGR2HSV))
            self.assertIsNotNone(candidate, scale)
            self.assertEqual(candidate.count, 3)
            self.assertLessEqual(candidate.span[0], 352 * scale)
            self.assertGreater(candidate.span[1], 352 * scale)

    def test_other_guide_mechanisms_are_not_freeze(self):
        for path in ROOT.glob("*.png"):
            if path.name == "ice.png" or path.name.startswith("training_"):
                continue
            with self.subTest(path=path.name):
                self.assertIsNone(read_freeze_candidate(read(path)))

    def test_training_examples_wire_all_counters_but_are_not_holdouts(self):
        for count in (1, 2, 3):
            candidate = read_freeze_candidate(read(ROOT / f"training_stage_{count}.png"))
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.count, count)

    def test_matching_digit_without_ice_colour_is_rejected(self):
        hsv = read(ROOT / "training_stage_3.png")
        cyan = cv2.inRange(hsv, (85, 80, 110), (115, 255, 255))
        hsv[cyan > 0] = (0, 0, 0)
        self.assertIsNone(read_freeze_candidate(hsv))
        self.assertIsNone(read_freeze_candidate(np.zeros((8, 50, 3), np.uint8)))
        self.assertIsNone(read_freeze_candidate(np.full((19, 244, 3), (100, 255, 255), np.uint8)))
