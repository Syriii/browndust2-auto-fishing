"""真实鱼获/升级截图与模拟设备验证连续弹窗，不连接游戏。"""

import configparser
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from bd2_fishing.game.fishing import qte, recovery, settlement
from bd2_fishing.game.fishing.settlement_rules import CatchResult
from bd2_fishing.infrastructure.settings import DEFAULT_CONFIG_CONTENT
from bd2_fishing.perception.ocr_types import OCRText
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class LevelUpTests(unittest.TestCase):
    def setUp(self):
        config = configparser.ConfigParser()
        config.read_string(DEFAULT_CONFIG_CONTENT)
        config.set("time", "fish_end_wait_time", "0.4")
        config.set("recovery", "page_wait_seconds", "0.4")
        self.observer = settlement.CatchObserver(Mock(), config, Rect(0, 0, 945, 532))
        self.strategy = qte.FrostStraitQTEStrategy(config, self.observer.window)
        self.strategy.catch_observer = self.observer
        self.root = Path(__file__).parents[1] / "fixtures/catch_result"
        self.reward = self.load("level_up_reward_20260910.png")
        self.level = self.load("level_up_holdout_20260910.png")
        self.idle = self.load("idle_day_945_180022.png")
        self.stages = [self.reward, self.level, self.idle]
        self.stage, self.clock = 0, 0.0
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.input = stack.enter_context(patch.object(recovery, "game_input"))
        self.input.click.side_effect = self.next_stage
        capture = stack.enter_context(patch.object(settlement, "FeedbackCapture"))
        self.camera = capture.return_value.__enter__.return_value
        self.camera.grab.side_effect = lambda: self.stages[self.stage]
        stack.enter_context(
            patch.object(settlement.window, "WindowGuard", return_value=lambda: None)
        )
        stack.enter_context(patch.object(control, "sleep", side_effect=self.sleep))
        stack.enter_context(
            patch.object(settlement.time, "monotonic", side_effect=lambda: self.clock)
        )
        stack.enter_context(
            patch.object(
                settlement,
                "read_settlement_texts",
                return_value=[OCRText("神仙鱼×1", 0.99), OCRText("17.8cm", 0.99)],
            )
        )

    def load(self, name):
        return cv2.imread(str(self.root / name))

    def sleep(self, seconds):
        self.clock += seconds

    def next_stage(self, *args):
        self.stage = min(self.stage + 1, len(self.stages) - 1)

    def test_real_level_up_source_and_independent_frame_are_identified(self):
        for name in ("level_up_source_20260910.png", "level_up_holdout_20260910.png"):
            frame = self.load(name)
            self.assertTrue(self.observer._panel_open(frame))
            kind, scores = self.observer.panel_reader.inspect(frame, close_visible=True)
            self.assertEqual(kind, "level_up", scores)
            self.assertTrue(all(score >= 0.88 for score in scores.values()), scores)

    def test_new_night_and_day_frames_with_independent_holdouts(self):
        from bd2_fishing.game.fishing.panels import SettlementPanelReader

        for name in (
            "level_up_night_20260913.png",
            "level_up_night_holdout_20260913.png",
            "level_up_day_holdout_20260913.png",
        ):
            for width, height in ((945, 532), (1192, 666), (1280, 720)):
                with self.subTest(name=name, size=(width, height)):
                    frame = cv2.resize(self.load(name), (width, height))
                    reader = SettlementPanelReader(Rect(0, 0, width, height))
                    kind, scores = reader.inspect(frame, close_visible=reader.is_open(frame))
                    self.assertEqual(kind, "level_up", scores)

    def test_each_fixed_label_is_required_in_night_fallback(self):
        reader = self.observer.panel_reader
        for left, top, right, bottom in reader.LABEL_BOUNDS:
            frame = self.load("level_up_night_holdout_20260913.png")
            frame[top - 3 : bottom + 3, left - 3 : right + 3] = 0
            self.assertNotEqual(reader.inspect(frame, close_visible=True)[0], "level_up")

    def test_lost_upgrade_click_retries_then_confirms_idle(self):
        self.stages = [self.reward, self.load("level_up_night_20260913.png"), self.idle]
        self.observer.config.set("time", "fish_end_wait_time", "4")
        calls = []

        def click(*point):
            calls.append((self.clock, point))
            if len(calls) != 2:  # First upgrade click is not acted on by the game.
                self.next_stage()

        self.input.click.side_effect = click
        self.strategy._finish_fishing()
        self.assertEqual(len(calls), 3)
        self.assertGreaterEqual(calls[2][0] - calls[1][0], 2)
        self.assertEqual(calls[2][1], (472, 492))
        self.assertTrue(self.observer.evidence_metadata["resume_confirmed"])
        self.assertEqual(self.observer.result.status, "caught")

    def test_upgrade_retries_cool_down_and_history_stays_bounded(self):
        self.stage = 1
        self.input.click.side_effect = None
        self.observer.inspect_current_page()
        for count in range(1, 21):
            self.assertTrue(recovery._close_new_panel(self.strategy, self.observer))
            self.assertFalse(recovery._close_new_panel(self.strategy, self.observer))
            meta = self.observer.evidence_metadata
            delay = 2 if count < 3 else 30
            self.assertAlmostEqual(meta["level_up_retry_at"] - self.clock, delay)
            self.clock = meta["level_up_retry_at"]
        self.assertEqual(len(meta["panel_close_history"]), 16)
        self.assertEqual(meta["level_up_close_attempts"], 20)
        self.assertEqual(meta["closed_panel_kinds"], ["level_up"])

    def test_retry_does_not_click_after_page_changes_or_stop(self):
        self.stage = 1
        self.input.click.side_effect = None
        self.observer.inspect_current_page()
        recovery._close_new_panel(self.strategy, self.observer)
        self.clock += 3
        self.stage = 2
        with self.assertRaises(recovery.RoundObservationError):
            recovery._close_new_panel(self.strategy, self.observer)
        self.input.click.assert_called_once()
        self.stage = 1
        self.observer.inspect_current_page()
        self.input.moveTo.side_effect = control.RunStopped("focus lost")
        with self.assertRaises(control.RunStopped):
            recovery._close_new_panel(self.strategy, self.observer)
        self.input.click.assert_called_once()

    def test_title_labels_and_close_prompt_are_all_required(self):
        reader = self.observer.panel_reader
        self.assertIsNone(reader.inspect(self.level, close_visible=False)[0])
        for left, top, right, bottom in reader.LEVEL_BOUNDS.values():
            partial = self.level.copy()
            partial[top - 3 : bottom + 3, left - 3 : right + 3] = 0
            self.assertNotEqual(reader.inspect(partial, close_visible=True)[0], "level_up")
        for frame in (
            self.reward,
            self.idle,
            self.load("loading_945.png"),
            np.zeros_like(self.idle),
        ):
            self.assertNotEqual(reader.inspect(frame, close_visible=True)[0], "level_up")

    def test_reward_then_upgrade_then_idle_preserves_catch_and_closes_each_once(self):
        self.strategy._finish_fishing()
        self.assertEqual(self.input.click.call_count, 2)
        self.assertEqual(self.observer.result.status, "caught")
        self.assertEqual(self.observer.result.size_cm, 17.8)
        metadata = self.observer.evidence_metadata
        self.assertEqual(metadata["closed_panel_kinds"], ["result", "level_up"])
        self.assertTrue(metadata["resume_confirmed"])
        self.assertTrue(
            np.array_equal(self.observer.evidence_frames["panel_before_result.png"], self.reward)
        )
        self.assertTrue(
            np.array_equal(self.observer.evidence_frames["panel_before_level_up.png"], self.level)
        )
        self.assertEqual(
            [event["status"] for event in metadata["panel_close_history"]], ["sent", "sent"]
        )

    def test_late_upgrade_after_prior_error_is_closed_and_recovery_continues(self):
        self.stage = 1
        self.observer.result = CatchResult("caught", "confirmed reward")
        self.observer.evidence_metadata["panel_close_attempted"] = True
        self.strategy.play_qte = Mock(side_effect=recovery.RoundObservationError("previous close"))
        self.strategy._stop_feedback = Mock()
        with (
            patch.object(self.observer, "finalize") as finalize,
            patch.object(self.observer, "wait_for_evidence"),
        ):
            settlement.run_observed_qte(self.strategy, Mock())
        self.input.click.assert_called_once()
        self.assertEqual(self.observer.evidence_metadata["round_recovery"]["status"], "resumed")
        self.assertEqual(self.observer.result.status, "caught")
        finalize.assert_called_once_with("round_unconfirmed")

    def test_same_upgrade_stuck_does_not_repeat_clicks(self):
        self.stages = [self.reward, self.level]
        with self.assertRaises(recovery.RoundObservationError):
            self.strategy._finish_fishing()
        self.assertEqual(self.input.click.call_count, 2)
        self.assertFalse(self.observer.evidence_metadata["resume_confirmed"])

    def test_same_reward_stuck_does_not_gain_second_click_permission(self):
        self.stages = [self.reward]
        with self.assertRaises(recovery.RoundObservationError):
            self.strategy._finish_fishing()
        self.input.click.assert_called_once()

    def prepare_exhausted_notice(self):
        self.stages = [
            self.load("notice_150302_20260913.png"),
            self.load("notice_150302_reward_20260913.png"),
            self.idle,
        ]
        self.observer.engine.detect_and_recognize.return_value = [
            OCRText("已耗尽体力。", 0.99),
            OCRText("error:150302", 0.99),
        ]
        self.observer.inspect_current_page()

    def test_overlay_close_does_not_consume_reward_close(self):
        self.prepare_exhausted_notice()
        recovery.close_confirmed_panel(self.strategy, self.observer)
        self.assertEqual(self.input.click.call_count, 2)
        self.assertEqual(self.input.click.call_args_list[0].args, (472, 292))
        metadata = self.observer.evidence_metadata
        self.assertEqual(metadata["closed_panel_kinds"], ["exhausted_notice", "result"])
        self.assertTrue(metadata["resume_confirmed"])
        self.assertTrue(
            np.array_equal(
                self.observer.evidence_frames["panel_before_result.png"],
                self.stages[1],
            )
        )

    def test_notice_retries_are_cooled_down_and_do_not_exhaust_reward_permission(self):
        self.prepare_exhausted_notice()
        self.input.click.side_effect = None
        for count in range(1, 5):
            self.assertTrue(recovery._close_new_panel(self.strategy, self.observer))
            self.assertFalse(recovery._close_new_panel(self.strategy, self.observer))
            metadata = self.observer.evidence_metadata
            self.assertAlmostEqual(
                metadata["exhausted_notice_retry_at"] - self.clock, 2 if count < 3 else 30
            )
            self.clock = metadata["exhausted_notice_retry_at"]
        self.assertNotIn("result", metadata["closed_panel_kinds"])

    def test_notice_wrong_code_or_low_confidence_never_clicks(self):
        self.prepare_exhausted_notice()
        for code, score in [("150402", 0.99), ("1503020", 0.99), ("150302", 0.5)]:
            self.observer.engine.detect_and_recognize.return_value = [
                OCRText("已耗尽体力。", 0.99),
                OCRText(f"error:{code}", score),
            ]
            with self.assertRaises(recovery.RoundObservationError):
                recovery._close_new_panel(self.strategy, self.observer)
        self.input.click.assert_not_called()
        self.assertNotIn("closed_panel_kinds", self.observer.evidence_metadata)

    def test_notice_disappearing_during_ocr_does_not_click_underlying_reward(self):
        self.prepare_exhausted_notice()

        def read(image):
            self.stage = 1
            return [OCRText("已耗尽体力。", 0.99), OCRText("error:150302", 0.99)]

        self.observer.engine.detect_and_recognize.side_effect = read
        with self.assertRaises(recovery.RoundObservationError):
            recovery._close_new_panel(self.strategy, self.observer)
        self.input.click.assert_not_called()

    def test_recovery_handles_notice_reward_then_idle_without_reentry(self):
        self.prepare_exhausted_notice()
        with patch.object(recovery, "_try_reentry") as reenter:
            self.assertTrue(
                recovery.recover_round(
                    self.strategy, self.observer, recovery.RoundObservationError("layered notice")
                )
            )
        reenter.assert_not_called()
        self.assertEqual(self.input.click.call_count, 2)
        self.assertEqual(self.observer.evidence_metadata["round_recovery"]["status"], "resumed")

    def test_panel_kind_changes_during_preclick_check_sends_no_click(self):
        self.stage = 1
        self.observer.inspect_current_page()
        self.stage = 0
        with self.assertRaises(recovery.RoundObservationError):
            recovery.close_confirmed_panel(self.strategy, self.observer)
        self.input.click.assert_not_called()

    def test_stop_between_reward_and_upgrade_propagates_without_second_click(self):
        def move(*args):
            if self.stage == 1:
                raise control.RunStopped("focus changed")

        self.input.moveTo.side_effect = move
        with self.assertRaises(control.RunStopped):
            self.strategy._finish_fishing()
        self.input.click.assert_called_once()

    def test_returning_to_old_panel_does_not_reset_click_budget(self):
        self.stages = [self.reward, self.level, self.reward]
        with self.assertRaises(recovery.RoundObservationError):
            self.strategy._finish_fishing()
        self.assertEqual(self.input.click.call_count, 2)

    def test_late_new_panel_gets_full_response_budget(self):
        self.observer.config.set("time", "fish_end_wait_time", "30")
        self.observer.inspect_current_page()

        def delayed_frame():
            if self.stage == 1:
                return self.reward if self.clock < 29.5 else self.level
            if self.stage == 2:
                return self.level if self.clock < 50 else self.idle
            return self.reward

        self.camera.grab.side_effect = delayed_frame
        recovery.close_confirmed_panel(self.strategy, self.observer)
        self.assertGreaterEqual(self.clock, 50)
        self.assertLess(self.clock, 60)
        self.assertEqual(self.input.click.call_count, 4)
        self.assertTrue(self.observer.evidence_metadata["resume_confirmed"])
