"""下午真实按键失败帧：先拒绝残色，保留有效黄条原有膨胀与蓝区回退。"""

import configparser
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

import cv2
import numpy as np

from bd2_fishing.game.fishing.mechanics.regions import read_mechanism_regions
from bd2_fishing.game.fishing.qte import AbyssMawQTEStrategy, FrostStraitQTEStrategy
from bd2_fishing.infrastructure.settings import DEFAULT_CONFIG_CONTENT
from bd2_fishing.perception import image as vision
from bd2_fishing.runtime import geometry
from bd2_fishing.runtime.geometry import Rect

FIXTURES = Path(__file__).parents[1] / "fixtures/qte_control/afternoon_misses"


def strategy(cls=FrostStraitQTEStrategy, tolerance=0, width=945, height=532):
    config = configparser.ConfigParser()
    config.read_string(DEFAULT_CONFIG_CONTENT)
    config.set("roi", "qte_press_tolerance_pixels", str(tolerance))
    result = cls(config, Rect(0, 0, width, height))
    result._qte_trace = Mock()
    result._press_qte = Mock()
    return result


def read_frame(controller, sample):
    bgr = cv2.imread(str(FIXTURES / (sample + "_decision.png")))
    return controller._split_roi_and_time(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV))[1]


def previous_mask(controller, hsv):
    kernel = geometry.scale_pixel_length(
        7, controller.pixel_threshold_scale.width_factor, minimum=3
    )
    kernel += kernel % 2 == 0
    return vision.create_color_mask(
        controller.yellow_range.lower,
        controller.yellow_range.upper,
        hsv,
        is_dilate=True,
        dilate_kernel_size=(kernel, kernel),
        dilate_iterations=2,
    )


class YellowSourceTests(TestCase):
    def test_m13_obscured_fragments_do_not_authorize_press(self):
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            controller = strategy(cls)
            hsv = read_frame(controller, "M13")
            cursor = controller._find_cursor_x(hsv)
            regions = read_mechanism_regions(hsv)
            self.assertFalse(regions.blocked[cursor])
            self.assertTrue(regions.mask_target(previous_mask(controller, hsv))[:, cursor].any())
            for _ in range(3):
                controller._track_targets(hsv, cursor, regions)
            controller._press_qte.assert_not_called()

    def test_clear_real_targets_and_clone_case_are_not_rejected_as_obscured(self):
        for name in ("M03", "M07", "M10", "M15"):
            controller = strategy()
            hsv = read_frame(controller, name)
            cursor = controller._find_cursor_x(hsv)
            controller._track_targets(hsv, cursor, read_mechanism_regions(hsv))
            controller._press_qte.assert_called_once()

    def test_sparse_real_failures_no_longer_authorize_yellow_or_spurious_blue(self):
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            for tolerance in (0, 4):
                for sample in ("M04", "M06", "M12", "M14"):
                    with self.subTest(strategy=cls.__name__, tolerance=tolerance, sample=sample):
                        controller = strategy(cls, tolerance)
                        hsv = read_frame(controller, sample)
                        cursor = controller._find_cursor_x(hsv)
                        regions = read_mechanism_regions(hsv)
                        self.assertIsNotNone(cursor)
                        self.assertTrue(previous_mask(controller, hsv)[:, cursor].any())
                        for _ in range(3):
                            controller._track_targets(hsv, cursor, regions)
                        controller._press_qte.assert_not_called()

    def test_valid_real_yellow_masks_preserve_existing_outer_boundary(self):
        # 这些只是边界保持样本，其中仍有待实测的 MISS，不能冒充成功回放。
        for sample in ("M02", "M03", "M05", "M07", "M08", "M09", "M10", "M15"):
            controller = strategy()
            hsv = read_frame(controller, sample)
            hsv = read_mechanism_regions(hsv).ordinary_pixels(hsv)
            with self.subTest(sample=sample):
                np.testing.assert_array_equal(
                    controller._yellow_mask(hsv), previous_mask(controller, hsv)
                )

    def test_target_colors_inside_obstruction_cannot_leak_out_after_dilation(self):
        controller = strategy()
        hsv = read_frame(controller, "M12")
        regions = read_mechanism_regions(hsv)
        cursor = controller._find_cursor_x(hsv)
        self.assertFalse(regions.blocked[cursor])
        old = regions.mask_target(previous_mask(controller, hsv))
        self.assertTrue(old[:, cursor].any())
        original = hsv.copy()
        cleaned = regions.ordinary_pixels(hsv)
        self.assertFalse(
            cv2.inRange(cleaned, controller.yellow_range.lower, controller.yellow_range.upper).any()
        )
        np.testing.assert_array_equal(hsv, original)

    def test_small_yellow_speck_does_not_disable_blue_only_entry(self):
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            controller = strategy(cls)
            hsv = np.zeros((19, 244, 3), np.uint8)
            blue = (controller.blue_range.lower + controller.blue_range.upper) // 2
            yellow = (controller.yellow_range.lower + controller.yellow_range.upper) // 2
            hsv[:, 80:125] = blue
            hsv[2, 180] = yellow
            regions = read_mechanism_regions(hsv)
            for _ in range(3):
                controller._track_targets(hsv, 100, regions)
            controller._press_qte.assert_called_once()
            self.assertEqual(controller._press_qte.call_args.kwargs["target"], "blue")

    def test_minimum_support_scales_and_valid_target_dilation_stays_identical(self):
        for width, height in ((875, 492), (945, 532), (1920, 1080)):
            controller = strategy(width=width, height=height)
            hsv = np.zeros((round(height * 19 / 532), round(width * 244 / 945), 3), np.uint8)
            hsv[:, 40:65] = (controller.yellow_range.lower + controller.yellow_range.upper) // 2
            np.testing.assert_array_equal(
                controller._yellow_mask(hsv), previous_mask(controller, hsv)
            )
            self.assertGreaterEqual(controller.yellow_source_min_pixels, 5)

    def test_all_real_pairs_match_preserved_hashes(self):
        import hashlib

        records = json.loads((FIXTURES / "manifest.json").read_text("utf-8"))
        self.assertEqual(len(records), 15)
        for record in records:
            for filename, digest in record["sha256"].items():
                self.assertEqual(
                    hashlib.sha256((FIXTURES / filename).read_bytes()).hexdigest(), digest
                )
