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

    def next_stage(self):
        self.stage = min(self.stage + 1, len(self.stages) - 1)

    def test_real_level_up_source_and_independent_frame_are_identified(self):
        for name in ("level_up_source_20260910.png", "level_up_holdout_20260910.png"):
            frame = self.load(name)
            self.assertTrue(self.observer._panel_open(frame))
            kind, scores = self.observer.panel_reader.inspect(frame, close_visible=True)
            self.assertEqual(kind, "level_up", scores)
            self.assertTrue(all(score >= 0.88 for score in scores.values()), scores)

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
        self.assertEqual(self.input.click.call_count, 2)
        self.assertTrue(self.observer.evidence_metadata["resume_confirmed"])
