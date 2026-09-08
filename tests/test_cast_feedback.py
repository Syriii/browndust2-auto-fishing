"""使用实机日志中的抛竿失败文本回归，不连接游戏。"""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np
from ocr import ocr_service
from ocr.ocr_utils import OCRContext, OCRRegions
from utils import Rect


class CastFeedbackTests(unittest.TestCase):
    def check_feedback(self, texts):
        capture = Mock(grab=Mock(return_value=np.zeros((49, 306, 3), dtype=np.uint8)))
        engine = Mock(detect_and_recognize=Mock(return_value=[
            SimpleNamespace(text=text, score=.97732, box=None) for text in texts
        ]))
        roi = Rect(278, 675, 584, 724)
        context = OCRContext(True, engine, OCRRegions(roi, roi, roi))
        self.addCleanup(lambda: engine.detect_and_recognize.assert_called_once())
        self.addCleanup(lambda: capture.grab.assert_called_once_with(roi))
        return ocr_service.check_backpack_if_full(capture, context)

    def test_recorded_cast_failure_signals_recovery_and_exposes_original_text(self):
        text = "当前位置无法抛竿。请移至船边重新尝试。"
        with self.assertLogs("ocr.ocr_service", level="WARNING") as logs:
            with self.assertRaisesRegex(ocr_service.CastPositionBlocked, "当前位置无法抛竿"):
                self.check_feedback([text])
        self.assertIn(text, logs.output[-1])

    def test_split_cast_failure_still_signals_recovery(self):
        with self.assertLogs("ocr.ocr_service", level="WARNING"), self.assertRaises(ocr_service.CastPositionBlocked):
            self.check_feedback(["当前 位置", "无法抛竿。", "请移至船边重新尝试。"])

    def test_empty_unrelated_and_backpack_feedback_keep_existing_behavior(self):
        for texts, full in (([], False), (["深渊巨口"], False), (["背包已满，请清理背包"], True)):
            with self.subTest(texts=texts):
                self.assertEqual(self.check_feedback(texts), full)


if __name__ == "__main__":
    unittest.main()
