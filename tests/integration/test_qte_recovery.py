"""离线验证失败轮次恢复、证据关联和输入/取消边界，不连接游戏。"""

import configparser
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bd2_fishing.game.fishing import recovery, settlement
from bd2_fishing.game.fishing.settlement_rules import CatchResult
from bd2_fishing.game.fishing.tracing import QTEControlTimeout, trace_qte
from bd2_fishing.infrastructure import settings
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class FailingStrategy:
    qte_detail_log = False
    region = roi_pos = Rect(0, 0, 945, 532)
    longest_keep_time = 35

    def __init__(self, error):
        self.error = error
        self._feedback_config = configparser.ConfigParser()
        self._feedback_config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        self._feedback_config.set("recovery", "page_wait_seconds", "0")
        self._stop_feedback = Mock()
        self.catch_observer = Mock(
            evidence_metadata={},
            evidence_frames={},
            result=CatchResult(),
            inspect_current_page=Mock(return_value="idle"),
        )

    @trace_qte
    def play_qte(self, capture):
        raise self.error


class QTERecoveryTests(unittest.TestCase):
    def setUp(self):
        self.inputs = patch.object(recovery, "game_input").start()
        self.addCleanup(patch.stopall)
        patch.object(control, "sleep").start()

    def run_round(self, strategy):
        with self.assertLogs("bd2_fishing.game.fishing", level="WARNING"):
            settlement.run_observed_qte(strategy, Mock())

    def test_timeout_on_idle_continues_and_preserves_error_and_result(self):
        strategy = FailingStrategy(QTEControlTimeout("35 seconds"))
        before = object()
        strategy.catch_observer.evidence_frames["settlement.png"] = before
        self.run_round(strategy)
        observer = strategy.catch_observer
        self.assertEqual(observer.result.status, "unknown")
        details = observer.evidence_metadata["round_recovery"]
        self.assertEqual(details["status"], "resumed")
        self.assertIn("QTEControlTimeout", details["traceback"])
        self.assertIs(observer.evidence_frames["failure_settlement.png"], before)
        self.assertEqual(strategy._stop_feedback.call_count, 2)
        observer.wait_until_idle.assert_called_once()
        observer.finalize.assert_called_once_with("control_timeout")
        self.assertEqual(self.inputs.mock_calls, [])

    def test_panel_requires_fresh_confirmation_and_only_one_click(self):
        strategy = FailingStrategy(recovery.RoundObservationError("late settlement"))
        strategy.catch_observer.inspect_current_page.side_effect = ["panel", "panel"]
        self.run_round(strategy)
        self.inputs.click.assert_called_once_with()
        strategy.catch_observer.wait_until_idle.assert_called_once()
        strategy.catch_observer.finalize.assert_called_once_with("round_unconfirmed")

    def test_panel_changed_before_click_preserves_original_error_and_sends_no_click(self):
        error = QTEControlTimeout("late")
        strategy = FailingStrategy(error)
        strategy.catch_observer.inspect_current_page.side_effect = ["panel", "unrecognized"]
        with self.assertRaises(QTEControlTimeout) as raised:
            self.run_round(strategy)
        self.assertIs(raised.exception, error)
        self.inputs.click.assert_not_called()
        self.assertEqual(
            strategy.catch_observer.evidence_metadata["round_recovery"]["status"], "failed"
        )

    def test_unknown_unavailable_and_active_qte_do_not_authorize_input(self):
        for state in ("unrecognized", "unavailable", "qte_active"):
            with self.subTest(state=state):
                strategy = FailingStrategy(QTEControlTimeout(state))
                strategy.catch_observer.inspect_current_page.return_value = state
                with self.assertRaises(QTEControlTimeout):
                    self.run_round(strategy)
                strategy.catch_observer.wait_until_idle.assert_not_called()
        self.assertEqual(self.inputs.mock_calls, [])

    def test_transition_to_idle_during_budget_allows_continuation(self):
        strategy = FailingStrategy(QTEControlTimeout("late"))
        strategy._feedback_config.set("recovery", "page_wait_seconds", "10")
        strategy.catch_observer.inspect_current_page.side_effect = ["unrecognized", "idle"]
        self.run_round(strategy)
        self.assertEqual(
            len(strategy.catch_observer.evidence_metadata["round_recovery"]["samples"]), 2
        )

    def test_stop_during_recovery_is_propagated_and_finalized_as_interruption(self):
        strategy = FailingStrategy(QTEControlTimeout("late"))
        strategy.catch_observer.inspect_current_page.side_effect = control.RunStopped("focus")
        with self.assertRaisesRegex(control.RunStopped, "focus"):
            self.run_round(strategy)
        strategy.catch_observer.finalize.assert_called_once_with("interrupted")
        self.assertEqual(
            strategy.catch_observer.evidence_metadata["round_recovery"]["status"], "interrupted"
        )
        self.assertEqual(self.inputs.mock_calls, [])

    def test_first_cleanup_failure_cannot_be_hidden_by_successful_retry(self):
        strategy = FailingStrategy(QTEControlTimeout("late"))
        strategy._stop_feedback.side_effect = [OSError("release"), None]
        with self.assertRaises(QTEControlTimeout):
            self.run_round(strategy)
        strategy.catch_observer.inspect_current_page.assert_not_called()
        strategy.catch_observer.finalize.assert_called_once_with("control_timeout")

    def test_unexpected_programming_error_does_not_enter_recovery(self):
        strategy = FailingStrategy(ValueError("invalid settings"))
        with self.assertRaises(ValueError):
            self.run_round(strategy)
        strategy.catch_observer.inspect_current_page.assert_not_called()

    def test_limit_counts_once_per_round_and_confirmed_catch_resets_it(self):
        strategy = FailingStrategy(QTEControlTimeout("late"))
        first = strategy.catch_observer
        recovery.check_unconfirmed_limit(strategy, first)
        self.run_round(strategy)
        self.assertEqual(strategy._unconfirmed_rounds, 1)
        strategy.catch_observer = Mock(
            evidence_metadata={}, evidence_frames={}, result=CatchResult()
        )
        strategy.catch_observer.inspect_current_page.return_value = "idle"
        self.run_round(strategy)
        strategy.catch_observer = Mock(
            evidence_metadata={}, evidence_frames={}, result=CatchResult()
        )
        with self.assertRaises(QTEControlTimeout):
            self.run_round(strategy)
        strategy.catch_observer.inspect_current_page.assert_not_called()
        caught = SimpleNamespace(evidence_metadata={}, result=CatchResult("caught", "reward"))
        recovery.check_unconfirmed_limit(strategy, caught)
        self.assertEqual(strategy._unconfirmed_rounds, 0)

    def test_disabled_recovery_stops_before_page_inspection(self):
        strategy = FailingStrategy(QTEControlTimeout("late"))
        strategy._feedback_config.set("recovery", "max_unconfirmed_rounds", "0")
        with self.assertRaises(QTEControlTimeout):
            self.run_round(strategy)
        strategy.catch_observer.inspect_current_page.assert_not_called()

    def test_existing_close_attempt_is_not_repeated_during_recovery(self):
        strategy = FailingStrategy(recovery.RoundObservationError("close pending"))
        strategy.catch_observer.evidence_metadata["panel_close_attempted"] = True
        strategy.catch_observer.inspect_current_page.return_value = "panel"
        with self.assertRaises(recovery.RoundObservationError):
            self.run_round(strategy)
        self.assertEqual(self.inputs.mock_calls, [])

    def test_failed_idle_confirmation_after_click_never_casts_or_clicks_again(self):
        strategy = FailingStrategy(QTEControlTimeout("late"))
        strategy.catch_observer.inspect_current_page.return_value = "panel"
        strategy.catch_observer.wait_until_idle.side_effect = recovery.RoundObservationError(
            "pending"
        )
        with self.assertRaises(QTEControlTimeout):
            self.run_round(strategy)
        self.inputs.click.assert_called_once_with()
        self.assertTrue(strategy.catch_observer.evidence_metadata["panel_close_attempted"])
