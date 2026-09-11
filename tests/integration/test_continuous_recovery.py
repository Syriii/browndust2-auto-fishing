"""9 月 11 日等待页中断原图及长时间恢复回放；不操作游戏。"""

import configparser
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2

from bd2_fishing.game.fishing import qte, recovery
from bd2_fishing.game.fishing.scene import FishingSceneReader
from bd2_fishing.game.fishing.settlement_rules import CatchResult
from bd2_fishing.game.fishing.tracing import QTEControlTimeout
from bd2_fishing.game.navigation import reentry
from bd2_fishing.infrastructure.settings import DEFAULT_CONFIG_CONTENT
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class ContinuousRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.config = configparser.ConfigParser()
        self.config.read_string(DEFAULT_CONFIG_CONTENT)
        self.config.set("recovery", "max_unconfirmed_rounds", "2")
        self.region = Rect(26, 532, 971, 1064)
        self.clock = 0.0
        self.addCleanup(patch.stopall)
        patch.object(control, "sleep", side_effect=self.sleep).start()
        patch.object(recovery.time, "monotonic", side_effect=lambda: self.clock).start()
        self.inputs = patch.object(recovery, "game_input").start()
        self.reenter = patch.object(
            reentry, "reenter_fishing", side_effect=reentry.NavigationFailed("unrecognized")
        ).start()

    def sleep(self, seconds):
        self.clock += seconds

    def test_actual_stop_frame_continues_waiting_after_hundreds_of_unknown_results(self):
        frame = cv2.imread(
            str(
                Path(__file__).parents[1]
                / "fixtures/catch_result/waiting_interruption_20260911.png"
            )
        )
        reading = FishingSceneReader(self.config, self.region).inspect(frame)
        self.assertEqual(reading.state, "waiting")
        observer = Mock(
            evidence_metadata={},
            evidence_frames={"settlement.png": frame},
            result=CatchResult(),
            inspect_current_page=Mock(return_value=reading.state),
        )
        strategy = SimpleNamespace(_feedback_config=self.config, _unconfirmed_rounds=500)
        self.assertTrue(
            recovery.recover_round(strategy, observer, QTEControlTimeout("recorded timeout"))
        )
        self.assertEqual(strategy._unconfirmed_rounds, 501)
        self.assertEqual(observer.evidence_metadata["round_recovery"]["next_state"], "waiting")
        self.assertEqual(self.inputs.mock_calls, [])

    def test_stalled_fishing_escalates_to_reentry(self):
        self.reenter.side_effect = None
        observer = Mock(evidence_metadata={}, evidence_frames={}, result=CatchResult())
        strategy = SimpleNamespace(_feedback_config=self.config)
        self.assertTrue(
            recovery.recover_round(strategy, observer, recovery.FishingStalled("stuck"))
        )
        self.reenter.assert_called_once_with(observer)
        observer.inspect_current_page.assert_not_called()
        self.assertEqual(observer.evidence_metadata["round_recovery"]["next_state"], "idle")

    def test_failed_reentry_keeps_waiting_and_retries_after_cooldown(self):
        self.reenter.side_effect = [reentry.NavigationFailed("transition"), None]
        observer = Mock(
            evidence_metadata={},
            evidence_frames={},
            result=CatchResult(),
            inspect_current_page=Mock(return_value="unrecognized"),
        )
        strategy = SimpleNamespace(_feedback_config=self.config)
        self.assertTrue(
            recovery.recover_round(strategy, observer, recovery.FishingStalled("stuck"))
        )
        attempts = observer.evidence_metadata["round_recovery"]["reentry_attempts"]
        self.assertEqual([x["status"] for x in attempts], ["pending", "resumed"])
        self.assertGreaterEqual(attempts[1]["started_at"] - attempts[0]["started_at"], 30)

    def test_stop_during_reentry_is_not_swallowed(self):
        self.reenter.side_effect = control.RunStopped("manual")
        observer = Mock(evidence_metadata={}, evidence_frames={}, result=CatchResult())
        with self.assertRaises(control.RunStopped):
            recovery.recover_round(
                SimpleNamespace(_feedback_config=self.config),
                observer,
                recovery.FishingStalled("stuck"),
            )
        self.reenter.assert_called_once()

    def test_partially_closed_bug_must_finish_reentry_even_if_idle_looks_normal(self):
        observer = Mock(
            evidence_metadata={},
            evidence_frames={},
            result=CatchResult(),
            inspect_current_page=Mock(return_value="idle"),
        )

        def first_attempt(value):
            value.evidence_metadata["stamina_reentry"] = {"actions": [{"action": "close_150402"}]}
            self.reenter.side_effect = None
            raise reentry.NavigationFailed("closed but not returned")

        self.reenter.side_effect = first_attempt
        strategy = SimpleNamespace(_feedback_config=self.config)
        self.assertTrue(
            recovery.recover_round(strategy, observer, recovery.FishingStalled("stuck"))
        )
        self.assertEqual(self.reenter.call_count, 2)
        observer.wait_until_idle.assert_not_called()
        self.assertGreaterEqual(self.clock, 30)

    def test_unknown_page_waits_past_budget_without_clicking_and_keeps_bounded_samples(self):
        observer = Mock(
            evidence_metadata={},
            evidence_frames={},
            result=CatchResult(),
            inspect_current_page=Mock(side_effect=["unrecognized"] * 350 + ["waiting"] * 3),
        )
        strategy = SimpleNamespace(_feedback_config=self.config)
        self.assertTrue(recovery.recover_round(strategy, observer, QTEControlTimeout("late")))
        details = observer.evidence_metadata["round_recovery"]
        self.assertGreater(self.clock, 60)
        self.assertGreater(details["pending_windows"], 1)
        self.assertEqual(len(details["samples"]), 300)
        self.assertEqual(details["next_state"], "waiting")
        self.assertEqual(self.inputs.mock_calls, [])

    def test_active_qte_recovery_returns_qte_without_new_hook_input(self):
        observer = Mock(
            evidence_metadata={},
            evidence_frames={},
            result=CatchResult(),
            inspect_current_page=Mock(return_value="qte"),
        )
        strategy = SimpleNamespace(_feedback_config=self.config)
        self.assertTrue(recovery.recover_round(strategy, observer, QTEControlTimeout("late")))
        self.assertEqual(observer.evidence_metadata["round_recovery"]["next_state"], "qte")
        self.assertEqual(self.inputs.mock_calls, [])

    def test_no_qte_entry_exits_loading_in_three_seconds_without_ocr_or_input(self):
        frame = cv2.imread(
            str(
                Path(__file__).parents[1]
                / "fixtures/catch_result/waiting_interruption_20260911.png"
            )
        )
        strategy = qte.FrostStraitQTEStrategy(self.config, self.region)
        observer = Mock(evidence_metadata={})
        strategy.catch_observer = observer
        strategy._start_feedback = Mock()
        strategy._stop_feedback = Mock()
        roi = strategy.roi_pos
        cropped = frame[
            roi.top - self.region.top : roi.bottom - self.region.top,
            roi.left - self.region.left : roi.right - self.region.left,
        ]
        strategy._grab_qte_frames = Mock(return_value=cv2.cvtColor(cropped, cv2.COLOR_BGR2HSV))
        with patch.object(qte, "pydirectinput") as inputs:
            with self.assertRaisesRegex(QTEControlTimeout, "3 秒"):
                strategy.play_qte(Mock())
        self.assertLess(self.clock, 3.1)
        self.assertFalse(observer.evidence_metadata["qte_entry_timeout"]["timer_seen"])
        observer.finish.assert_not_called()
        self.assertEqual(inputs.mock_calls, [])
