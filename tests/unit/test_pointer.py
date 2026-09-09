"""用户确认的分身规则：真实正例、模糊帧及亮色干扰负例。"""

import unittest
from pathlib import Path

import cv2
import numpy as np

from bd2_fishing.game.fishing.pointer import read_pointer


class PointerTests(unittest.TestCase):
    def test_user_confirmed_clones_choose_bright_pointer(self):
        root = Path(__file__).parents[1] / "fixtures" / "qte_control"
        for name, expected in (("f05_observer_control.png", 170), ("f06_observer_control.png", 44)):
            with self.subTest(name=name):
                raw = cv2.imread(str(root / name))
                hsv = cv2.cvtColor(raw[21:40, 68:312], cv2.COLOR_BGR2HSV)
                result = read_pointer(hsv)
                self.assertEqual(result.x, expected)
                self.assertEqual(result.reason, "brightest_pointer")

    def scene(self):
        hsv = np.zeros((30, 240, 3), np.uint8)
        hsv[:, 30:100] = (99, 230, 255)  # 彩色条本身更亮，但不是光标。
        hsv[:, 180:210] = (25, 200, 255)
        return hsv

    def test_brightest_pointer_wins_over_more_pixels_and_colored_targets(self):
        hsv = self.scene()
        hsv[:, 45:48] = (110, 55, 215)  # 宽暗分身不能因像素多而胜出。
        hsv[:, 150] = (0, 0, 255)
        hsv[12:14, 120:124] = (0, 0, 255)  # 短高亮粒子。
        self.assertEqual(read_pointer(hsv).x, 150)

    def test_ambiguity_absent_target_and_dim_only_do_not_invent_pointer(self):
        hsv = self.scene()
        self.assertIsNone(read_pointer(hsv).x)
        hsv[:, 120] = (0, 0, 240)
        hsv[:, 150] = (0, 0, 245)
        self.assertEqual(read_pointer(hsv).reason, "ambiguous_brightness")
        hsv[:, 120] = (0, 0, 0)
        hsv[:, 150] = (110, 55, 200)
        self.assertEqual(read_pointer(hsv).reason, "only_dim_candidates")
        self.assertIsNone(read_pointer(np.zeros((0, 0, 3), np.uint8)).x)

    def test_uniform_white_and_horizontal_borders_are_not_pointers(self):
        hsv = np.full((30, 240, 3), (0, 0, 255), np.uint8)
        self.assertIsNone(read_pointer(hsv).x)
        hsv[:] = 0
        hsv[:2] = (0, 0, 255)
        hsv[-2:] = (0, 0, 255)
        self.assertIsNone(read_pointer(hsv).x)

    def test_geometry_scales_with_window(self):
        hsv = self.scene()
        hsv[:, 55] = (110, 50, 215)
        hsv[:, 150] = (0, 0, 255)
        for scale in (1, 2, 3):
            enlarged = cv2.resize(hsv, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            self.assertLess(abs(read_pointer(enlarged).x - 150 * scale), scale)
