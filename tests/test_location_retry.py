"""复现只识别到“更改 / N”的地点识别，并验证有限重试和取消。"""

from unittest.mock import Mock, patch
import unittest

from ocr import ocr_service
from ocr.ocr_enum import FishingLocation
from ocr.ocr_utils import OCRContext, OCRRegions
from utils import Rect
import run_control


class LocationRetryTests(unittest.TestCase):
    def setUp(self):
        roi = Rect(112, 616, 261, 650)
        self.context = OCRContext(True, Mock(), OCRRegions(roi, roi, roi))

    def test_recorded_partial_result_then_no_frame_then_location(self):
        with patch.object(ocr_service, "get_texts_from_ocr", side_effect=[["更改", "N"], None, ["深渊巨口"]]) as read, \
                patch.object(run_control, "sleep") as sleep, self.assertLogs("ocr.ocr_service", level="WARNING") as logs:
            location = ocr_service.detect_location_from_ocr(Mock(), self.context, True)
        self.assertEqual(location, FishingLocation.ABYSS_MAW)
        self.assertEqual(read.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("更改", logs.output[0])
        self.assertIn("112, 616, 261, 650", logs.output[0])

    def test_persistent_failure_is_bounded_without_assuming_previous_location(self):
        with patch.object(ocr_service, "get_texts_from_ocr", return_value=["更改", "N"]) as read, \
                patch.object(run_control, "sleep") as sleep, self.assertLogs("ocr.ocr_service", level="WARNING"):
            self.assertIsNone(ocr_service.detect_location_from_ocr(Mock(), self.context, True))
        self.assertEqual(read.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_immediate_success_does_not_wait_or_repeat(self):
        with patch.object(ocr_service, "get_texts_from_ocr", return_value=["深渊巨口"]) as read, \
                patch.object(run_control, "sleep") as sleep:
            self.assertEqual(ocr_service.detect_location_from_ocr(Mock(), self.context, True), FishingLocation.ABYSS_MAW)
        read.assert_called_once()
        sleep.assert_not_called()

    def test_cancel_during_retry_prevents_next_ocr(self):
        with patch.object(ocr_service, "get_texts_from_ocr", return_value=[]) as read, \
                patch.object(run_control, "sleep", side_effect=run_control.RunStopped()), \
                self.assertLogs("ocr.ocr_service", level="WARNING"), self.assertRaises(run_control.RunStopped):
            ocr_service.detect_location_from_ocr(Mock(), self.context, True)
        read.assert_called_once()

    def test_disabled_auto_selection_does_not_retry(self):
        with patch.object(ocr_service, "get_texts_from_ocr") as read, patch.object(run_control, "sleep") as sleep:
            self.assertIsNone(ocr_service.detect_location_from_ocr(Mock(), self.context, False))
        read.assert_not_called()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
