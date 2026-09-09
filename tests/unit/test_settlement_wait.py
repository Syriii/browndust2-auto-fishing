"""真实过渡/奖励图片与模拟时钟验证结算等待，不接触游戏。"""

import configparser
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import cv2

from bd2_fishing.game.fishing import qte, settlement
from bd2_fishing.infrastructure import settings
from bd2_fishing.perception.ocr_types import OCRText
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class SettlementWaitTests(unittest.TestCase):
    def setUp(self):
        self.config = configparser.ConfigParser()
        self.config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        self.config.set("time", "fish_end_wait_time", "0.4")
        self.region = Rect(0, 0, 945, 532)
        self.observer = settlement.CatchObserver(Mock(), self.config, self.region)
        root = Path(__file__).parents[1] / "fixtures" / "catch_result"
        self.loading = cv2.imread(str(root / "loading_945.png"))
        self.caught = cv2.imread(str(root / "caught_ready_20260909.png"))
        self.clock = 0.0
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.camera = Mock()
        capture = self.stack.enter_context(patch.object(settlement, "FeedbackCapture"))
        capture.return_value.__enter__.return_value = self.camera
        self.stack.enter_context(
            patch.object(settlement.window, "WindowGuard", return_value=lambda: None)
        )
        self.stack.enter_context(
            patch.object(settlement.time, "monotonic", side_effect=lambda: self.clock)
        )
        self.sleep = self.stack.enter_context(
            patch.object(control, "sleep", side_effect=self.advance)
        )
        self.ocr = self.stack.enter_context(
            patch.object(
                settlement,
                "read_settlement_texts",
                return_value=[OCRText("蓝龙海神x1", 0.97), OCRText("3.1cm", 0.99)],
            )
        )

    def advance(self, seconds):
        self.clock += seconds

    def test_transition_then_reward_confirms_panel_and_keeps_both_times(self):
        self.camera.grab.side_effect = [self.loading, self.caught]
        self.observer.finish()
        self.assertEqual(self.camera.grab.call_count, 2)
        self.assertEqual(self.observer.result.status, "caught")
        self.assertEqual(self.observer.result.size_cm, 3.1)
        self.assertEqual(self.observer.evidence_metadata["first_settlement_at_monotonic"], 0)
        self.assertEqual(self.observer.evidence_metadata["captured_at_monotonic"], 0.2)
        self.ocr.assert_called_once()

    def test_already_ready_panel_has_no_added_poll_wait(self):
        self.camera.grab.return_value = self.caught
        self.observer.finish()
        self.sleep.assert_not_called()
        self.camera.grab.assert_called_once()

    def test_persistent_transition_is_bounded_and_never_clicked(self):
        self.camera.grab.return_value = self.loading
        strategy = qte.FrostStraitQTEStrategy(self.config, self.region)
        strategy.catch_observer = self.observer
        with patch.object(qte.pydirectinput, "click") as click:
            with self.assertRaisesRegex(TimeoutError, "未确认结算面板"):
                strategy._finish_fishing()
        click.assert_not_called()
        self.assertEqual(self.camera.grab.call_count, 3)
        self.assertEqual(self.clock, 0.4)
        self.ocr.assert_not_called()
        self.assertEqual(self.observer.result.status, "unknown")

    def test_stop_during_wait_retains_first_frame_without_further_capture(self):
        self.camera.grab.return_value = self.loading
        self.sleep.side_effect = control.RunStopped("stop")
        with self.assertRaises(control.RunStopped):
            self.observer.finish()
        self.camera.grab.assert_called_once()
        self.assertIn("settlement.png", self.observer.evidence_frames)
        self.ocr.assert_not_called()

    def test_unavailable_frames_stop_at_deadline(self):
        self.camera.grab.return_value = None
        with self.assertRaisesRegex(RuntimeError, "未取得有效截图"):
            self.observer.finish()
        self.assertEqual(self.camera.grab.call_count, 3)
        self.assertFalse(self.observer.evidence_metadata["panel_open"])
        self.ocr.assert_not_called()
