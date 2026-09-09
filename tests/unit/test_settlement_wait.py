"""真实过渡/奖励图片与模拟时钟验证结算等待，不接触游戏。"""

import configparser
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from bd2_fishing.game.fishing import qte, settlement
from bd2_fishing.game.fishing.page import FishingPageReader
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
        self.idle = cv2.imread(str(root / "idle_20260909.png"))
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

    def test_reward_recheck_uses_real_945_glyph_with_independent_background(self):
        root = Path(__file__).parents[1] / "fixtures" / "catch_result"
        for name in ("caught_close_source_945.png", "caught_close_holdout_945.png"):
            frame = cv2.imread(str(root / name))
            self.camera.grab.return_value = frame
            self.assertEqual(self.observer.inspect_current_page(), "panel", name)
            # 奖励和大鱼仍在，单独去掉关闭字样不能获准点击。
            missing_text = frame.copy()
            missing_text[482:504, 432:515] = 0
            self.camera.grab.return_value = missing_text
            self.assertEqual(self.observer.inspect_current_page(), "unrecognized")

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

    def test_configured_long_budget_really_observes_after_four_seconds(self):
        self.config.set("time", "fish_end_wait_time", "6")
        self.camera.grab.side_effect = [self.loading] * 25 + [self.caught]
        self.observer.finish()
        self.assertGreater(self.clock, 4)
        self.assertEqual(self.observer.result.status, "caught")

    def test_idle_requires_two_separated_valid_frames_and_keeps_unknown(self):
        self.camera.grab.side_effect = [self.idle, None, self.idle]
        self.observer.finish()
        self.assertNotEqual(self.observer.evidence_metadata["page_state"], "idle")
        self.camera.grab.side_effect = None
        self.camera.grab.return_value = self.idle
        self.observer.finish()
        self.assertEqual(self.observer.evidence_metadata["page_state"], "idle")
        self.assertEqual(self.observer.result.status, "unknown")

    def test_missing_or_partial_controls_never_enable_recovery(self):
        for frame in (self.loading, self.caught, np.zeros_like(self.idle), self.idle[:100]):
            self.assertFalse(self.observer.page_reader.inspect(frame)[0])
        frame = self.idle.copy()
        frame[:, :200] = 0
        self.assertFalse(self.observer.page_reader.inspect(frame)[0])

    def test_real_idle_variants_and_independent_frame_match_without_reward_false_positive(self):
        root = Path(__file__).parents[1] / "fixtures" / "catch_result"
        for name in (
            "normal.png",
            "normal_945.png",
            "escaped_scene.png",
            "idle_holdout_20260909.png",
        ):
            frame = cv2.imread(str(root / name))
            height, width = frame.shape[:2]
            self.assertTrue(FishingPageReader(Rect(0, 0, width, height)).inspect(frame)[0], name)

    def test_bright_button_background_keeps_arrow_identity_without_lowering_threshold(self):
        root = Path(__file__).parents[1] / "fixtures" / "catch_result"
        frame = cv2.imread(str(root / "idle_bright_background_20260909.png"))
        ready, scores = self.observer.page_reader.inspect(frame)
        self.assertTrue(ready, scores)
        self.assertGreaterEqual(scores["idle_movement"], 0.88)
        for x, y in FishingPageReader.ARROW_CENTERS.values():
            partial = frame.copy()
            partial[y - 8 : y + 9, x - 8 : x + 9] = 0
            self.assertFalse(self.observer.page_reader.inspect(partial)[0])
        for value in (0, 190, 255):
            self.assertFalse(self.observer.page_reader.inspect(np.full_like(frame, value))[0])

    def test_idle_recovery_does_not_click_and_continuation_is_bounded(self):
        strategy = qte.FrostStraitQTEStrategy(self.config, self.region)
        strategy.catch_observer = self.observer
        self.camera.grab.return_value = self.idle
        with patch.object(qte.pydirectinput, "click") as click:
            strategy._finish_fishing()
            strategy._finish_fishing()
            with self.assertRaisesRegex(RuntimeError, "续钓上限"):
                strategy._finish_fishing()
        click.assert_not_called()
        self.assertTrue(self.observer.evidence_metadata["resume_confirmed"])
        self.assertEqual(self.observer.result.status, "unknown")

    def test_page_change_before_click_never_clicks(self):
        strategy = qte.FrostStraitQTEStrategy(self.config, self.region)
        strategy.catch_observer = self.observer
        self.camera.grab.side_effect = [self.caught, self.caught, self.loading]
        with (
            patch.object(qte.pydirectinput, "moveTo"),
            patch.object(qte.pydirectinput, "click") as click,
        ):
            with self.assertRaisesRegex(TimeoutError, "关闭前"):
                strategy._finish_fishing()
        click.assert_not_called()

    def test_panel_still_visible_after_click_does_not_repeat_click(self):
        strategy = qte.FrostStraitQTEStrategy(self.config, self.region)
        strategy.catch_observer = self.observer
        self.camera.grab.return_value = self.caught
        with (
            patch.object(qte.pydirectinput, "moveTo"),
            patch.object(qte.pydirectinput, "click") as click,
        ):
            with self.assertRaisesRegex(TimeoutError, "未确认钓鱼待机"):
                strategy._finish_fishing()
        click.assert_called_once()
        self.assertEqual(self.observer.result.status, "caught")

    def test_observer_failure_without_page_evidence_never_clicks(self):
        strategy = qte.FrostStraitQTEStrategy(self.config, self.region)
        strategy.catch_observer = self.observer
        with (
            patch.object(self.observer, "finish", side_effect=ValueError("broken")),
            patch.object(qte.pydirectinput, "click") as click,
        ):
            with self.assertRaisesRegex(RuntimeError, "结算观察失败"):
                strategy._finish_fishing()
        click.assert_not_called()
