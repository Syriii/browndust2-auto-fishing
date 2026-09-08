"""使用夜间真实截图回归验证感叹号色相范围，不连接游戏或发送输入。"""

import configparser
import unittest
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]


class NightHookTests(unittest.TestCase):
    def setUp(self):
        config = configparser.ConfigParser()
        config.read(ROOT / "config.ini", encoding="utf-8-sig")
        self.lower = tuple(config.getint("hook", f"hook_lower_{key}")
                           for key in ("hue", "saturation", "value"))
        self.upper = tuple(config.getint("hook", f"hook_upper_{key}")
                           for key in ("hue", "saturation", "value"))
        self.threshold = round(220 * 1132 * 636 / (1152 * 648))

    def count(self, filename, upper=None):
        encoded = np.frombuffer((ROOT / "tests" / "fixtures" / filename).read_bytes(), np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        return cv2.countNonZero(cv2.inRange(hsv, self.lower, upper or self.upper))

    def test_actual_night_indicators_cross_existing_threshold(self):
        for filename, old_count, new_count in (
            ("night_hook_178.png", 178, 249),
            ("night_hook_183.png", 183, 233),
        ):
            with self.subTest(filename=filename):
                self.assertEqual(self.count(filename, (30, 120, 255)), old_count)
                self.assertLessEqual(old_count, self.threshold)
                self.assertEqual(self.count(filename), new_count)
                self.assertGreater(new_count, self.threshold)

    def test_night_scene_without_indicator_does_not_trigger(self):
        self.assertEqual(self.count("night_without_hook.png"), 0)


if __name__ == "__main__":
    unittest.main()
