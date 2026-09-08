"""复现只识别到“更改 / N”的地点识别，并验证有限重试和取消。"""

import unittest
from unittest.mock import Mock, patch

from bd2_fishing.game.islands import reading as island_reading
from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.game.observation import OCRContext, OCRRegions
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime.geometry import Rect


class LocationRetryTests(unittest.TestCase):
    def setUp(self):
        roi = Rect(112, 616, 261, 650)
        self.context = OCRContext(True, Mock(), OCRRegions(roi, roi, roi))

    def test_recorded_partial_result_then_no_frame_then_location(self):
        with (
            patch.object(
                island_reading,
                "get_texts_from_ocr",
                side_effect=[["更改", "N"], None, ["深渊巨口"]],
            ) as read,
            patch.object(run_control, "sleep") as sleep,
            self.assertLogs("bd2_fishing.game.islands.reading", level="WARNING") as logs,
        ):
            location = island_reading.detect_location_from_ocr(Mock(), self.context, True)
        self.assertEqual(location, FishingLocation.ABYSS_MAW)
        self.assertEqual(read.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("更改", logs.output[0])
        self.assertIn("112, 616, 261, 650", logs.output[0])

    def test_persistent_failure_is_bounded_without_assuming_previous_location(self):
        with (
            patch.object(island_reading, "get_texts_from_ocr", return_value=["更改", "N"]) as read,
            patch.object(run_control, "sleep") as sleep,
            self.assertLogs("bd2_fishing.game.islands.reading", level="WARNING"),
        ):
            self.assertIsNone(island_reading.detect_location_from_ocr(Mock(), self.context, True))
        self.assertEqual(read.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_immediate_success_does_not_wait_or_repeat(self):
        with (
            patch.object(island_reading, "get_texts_from_ocr", return_value=["深渊巨口"]) as read,
            patch.object(run_control, "sleep") as sleep,
        ):
            self.assertEqual(
                island_reading.detect_location_from_ocr(Mock(), self.context, True),
                FishingLocation.ABYSS_MAW,
            )
        read.assert_called_once()
        sleep.assert_not_called()

    def test_cancel_during_retry_prevents_next_ocr(self):
        with (
            patch.object(island_reading, "get_texts_from_ocr", return_value=[]) as read,
            patch.object(run_control, "sleep", side_effect=run_control.RunStopped()),
            self.assertLogs("bd2_fishing.game.islands.reading", level="WARNING"),
            self.assertRaises(run_control.RunStopped),
        ):
            island_reading.detect_location_from_ocr(Mock(), self.context, True)
        read.assert_called_once()

    def test_disabled_auto_selection_does_not_retry(self):
        with (
            patch.object(island_reading, "get_texts_from_ocr") as read,
            patch.object(run_control, "sleep") as sleep,
        ):
            self.assertIsNone(island_reading.detect_location_from_ocr(Mock(), self.context, False))
        read.assert_not_called()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
