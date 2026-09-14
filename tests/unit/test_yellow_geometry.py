"""首次经过黄条的实体分组、短时记忆和拒绝取证；全部输入模拟。"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import cv2
import numpy as np

from bd2_fishing.game.fishing.mechanics.regions import read_mechanism_regions
from bd2_fishing.game.fishing.mechanics.yellow_geometry import (
    YellowTargetMemory,
    read_yellow_geometry,
)
from bd2_fishing.game.fishing.qte import AbyssMawQTEStrategy, FrostStraitQTEStrategy
from tests.unit.test_yellow_source_evidence import strategy

ROOT = Path(__file__).parents[1] / "fixtures/qte_control/yellow_20260914"
DATA = json.loads((ROOT / "manifest.json").read_text(encoding="utf8"))


def mask_for(*spans):
    mask = np.zeros((19, 244), np.uint8)
    for a, b in spans:
        mask[:, a:b] = 255
    return mask


def read_frame(controller, filename):
    frame = cv2.imread(str(ROOT / filename))[96:138, 18:330]
    return controller._split_roi_and_time(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))[1]


class YellowGeometryTests(TestCase):
    def test_internal_speck_does_not_replace_target_boundary(self):
        mask = mask_for((107, 116), (125, 126), (128, 130))
        reading = read_yellow_geometry(mask, 120)
        self.assertEqual(reading.span, (107, 130))
        self.assertEqual(reading.source, "cursor_gap")
        self.assertEqual(reading.raw_spans, ((107, 116), (125, 126), (128, 130)))

    def test_real_two_sided_candidates_press_on_first_observation_and_not_twice(self):
        cases = [r for r in DATA["candidates"] if r["single_frame"]]
        self.assertEqual(len(cases), 32)
        for cls in (FrostStraitQTEStrategy, AbyssMawQTEStrategy):
            for item in cases:
                with self.subTest(strategy=cls.__name__, file=item["file"]):
                    controller = strategy(cls)
                    hsv = read_frame(controller, item["file"])
                    cursor = controller._find_cursor_x(hsv)
                    regions = read_mechanism_regions(hsv)
                    controller._track_targets(hsv, cursor, regions)
                    if cls is AbyssMawQTEStrategy and item["file"] in {"Y05.png", "Y39.png"}:
                        # 样本来自亚特兰蒂斯；巨口策略额外读到挡板时，禁止跨板修孔。
                        self.assertIsNotNone(
                            controller._qte_trace.observe.call_args.kwargs["blocker"]
                        )
                        controller._press_qte.assert_not_called()
                        continue
                    controller._press_qte.assert_called_once()
                    span = controller._yellow_geometry_reading.span
                    self.assertLessEqual(span[0], cursor)
                    self.assertLess(cursor, span[1])
                    controller._track_targets(hsv, cursor, regions)
                    controller._press_qte.assert_called_once()

    def test_scaled_hole_blockers_single_sided_and_wide_gap(self):
        for scale in (1, 2, 3):
            base = mask_for((107, 116), (125, 126), (128, 130))
            mask = cv2.resize(base, (244 * scale, 19 * scale), interpolation=cv2.INTER_NEAREST)
            self.assertEqual(
                read_yellow_geometry(mask, 120 * scale).span, (107 * scale, 130 * scale)
            )
            blocked = np.zeros(mask.shape[1], bool)
            blocked[121 * scale : 123 * scale] = True
            self.assertNotEqual(
                read_yellow_geometry(mask, 120 * scale, blocked).source, "cursor_gap"
            )
        for mask in (
            mask_for((107, 116)),
            mask_for((107, 109), (130, 132)),
            mask_for((107, 108), (120, 121)),
        ):
            self.assertNotEqual(read_yellow_geometry(mask, 117).source, "cursor_gap")

    def test_memory_needs_two_frames_then_current_both_edges_and_expires(self):
        memory = YellowTargetMemory()
        clear = mask_for((107, 130))
        weak = mask_for((107, 116), (129, 130))
        blocked = np.zeros(244, bool)

        def observe(mask, cursor, stamp):
            return memory.observe(
                read_yellow_geometry(mask, cursor, blocked), cursor, stamp, mask.shape, blocked
            )

        observe(clear, 160, 1)
        self.assertNotEqual(observe(weak, 120, 1.02).source, "confirmed_edges")
        observe(clear, 160, 2)
        observe(clear, 150, 2.02)
        self.assertEqual(observe(weak, 120, 2.04).source, "confirmed_edges")
        self.assertNotEqual(observe(mask_for((107, 116)), 120, 2.06).source, "confirmed_edges")
        observe(clear, 160, 3)
        observe(clear, 150, 3.02)
        self.assertEqual(observe(weak, 120, 3.15).source, "confirmed_edges")
        self.assertNotEqual(observe(weak, 120, 3.22).source, "confirmed_edges")

    def test_memory_clears_on_target_change_missing_frame_shape_and_obstruction(self):
        for failure in ("changed", "missing", "shape", "blocked"):
            controller = strategy()
            memory = controller._mechanism_policy.targets.yellow_geometry
            blocked = np.zeros(244, bool)
            for stamp in (1, 1.02):
                mask = mask_for((107, 130))
                memory.observe(read_yellow_geometry(mask, 160), 160, stamp, mask.shape, blocked)
            mask = mask_for((107, 116), (129, 130))
            if failure == "changed":
                mask = mask_for((105, 110), (128, 129), (180, 200))
            elif failure == "missing":
                controller._mechanism_policy.targets.invalidate()
            elif failure == "shape":
                mask = np.repeat(mask, 2, axis=0)
            else:
                blocked[120] = True
            reading = memory.observe(
                read_yellow_geometry(mask, 120, blocked), 120, 1.04, mask.shape, blocked
            )
            self.assertNotEqual(reading.source, "confirmed_edges", failure)

    def test_real_sequence_weak_edge_uses_previous_complete_target(self):
        seq = next(s for s in DATA["sequences"] if "ada08326" in s["zip"])
        controller = strategy()
        for item in seq["frames"]:
            hsv = read_frame(controller, item["file"])
            cursor = controller._find_cursor_x(hsv)
            with patch("bd2_fishing.game.fishing.qte.time.monotonic", return_value=item["stamp"]):
                controller._track_targets(hsv, cursor, read_mechanism_regions(hsv))
        self.assertEqual(controller._yellow_geometry_reading.source, "confirmed_edges")
        self.assertEqual(controller._press_qte.call_args.kwargs["cursor_x"], 58)

    def test_rejected_frames_are_bounded_and_keep_control_coordinates(self):
        controller = strategy()
        controller.catch_observer = SimpleNamespace(evidence_metadata={}, evidence_frames={})
        controller._decision_frame = np.zeros((42, 312, 3), np.uint8)
        controller._decision_captured_at = 5.0
        for stamp in np.arange(5, 10, 0.05):
            hsv = read_frame(controller, "Y02.png")
            cursor = controller._find_cursor_x(hsv)
            with patch("bd2_fishing.game.fishing.qte.time.monotonic", return_value=float(stamp)):
                controller._track_targets(hsv, cursor, read_mechanism_regions(hsv))
        records = controller.catch_observer.evidence_metadata["yellow_rejections"]
        self.assertEqual(len(records), 3)
        self.assertEqual(len(controller.catch_observer.evidence_frames), 3)
        self.assertGreaterEqual(records[1]["observed_at"] - records[0]["observed_at"], 0.25)
        self.assertEqual(records[0]["captured_at"], 5.0)
        self.assertTrue(records[0]["geometry"]["raw_spans"])
        controller._press_qte.assert_not_called()
