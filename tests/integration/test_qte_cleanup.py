"""执行、反馈清理和证据封存同时失败时仍保留原退出原因。"""

import unittest
from unittest.mock import Mock

from bd2_fishing.game.fishing.settlement import run_observed_qte
from bd2_fishing.game.fishing.tracing import QTEControlTimeout, trace_qte
from bd2_fishing.runtime.control import RunStopped
from bd2_fishing.runtime.geometry import Rect


class OfflineStrategy:
    qte_detail_log = False
    roi_pos = Rect(0, 0, 30, 20)
    longest_keep_time = 35

    def __init__(self, failure=None):
        self.failure = failure
        self._start_feedback = Mock()
        self._stop_feedback = Mock(side_effect=OSError("release failed"))
        self.catch_observer = Mock()

    @trace_qte
    def play_qte(self, capture):
        if self.failure is not None:
            raise self.failure


class QTECleanupTests(unittest.TestCase):
    def test_primary_exit_survives_both_cleanup_failures_and_still_finalizes(self):
        for failure, reason in (
            (RunStopped("user stop"), "interrupted"),
            (QTEControlTimeout("time limit"), "control_timeout"),
            (ValueError("recognition failed"), "exception:ValueError"),
        ):
            with self.subTest(reason=reason):
                strategy = OfflineStrategy(failure)
                with self.assertLogs("bd2_fishing.game.fishing", level="ERROR"):
                    with self.assertRaises(type(failure)) as raised:
                        run_observed_qte(strategy, Mock())
                self.assertIs(raised.exception, failure)
                self.assertEqual(strategy._stop_feedback.call_count, 2)
                self.assertEqual(len(failure.__notes__), 2)
                strategy.catch_observer.finalize.assert_called_once_with(reason)
                strategy.catch_observer.wait_for_evidence.assert_called_once()
                self.assertIsNone(strategy._qte_trace)

    def test_cleanup_failure_after_normal_return_stops_and_finalizes(self):
        strategy = OfflineStrategy()
        with self.assertLogs("bd2_fishing.game.fishing", level="ERROR"):
            with self.assertRaises(OSError):
                run_observed_qte(strategy, Mock())
        strategy.catch_observer.finalize.assert_called_once_with("exception:OSError")
        strategy.catch_observer.wait_for_evidence.assert_called_once()

    def test_finalizer_failure_does_not_replace_primary_stop(self):
        failure = RunStopped("user stop")
        strategy = OfflineStrategy(failure)
        strategy.catch_observer.finalize.side_effect = OSError("disk error")
        with self.assertLogs("bd2_fishing.game.fishing", level="ERROR"):
            with self.assertRaises(RunStopped) as raised:
                run_observed_qte(strategy, Mock())
        self.assertIs(raised.exception, failure)
        strategy.catch_observer.finalize.assert_called_once_with("interrupted")

    def test_cleanup_failure_is_not_swallowed_by_callers_handled_exception(self):
        for strategy in (OfflineStrategy(), Mock()):
            with self.subTest(strategy=type(strategy).__name__):
                strategy._stop_feedback.side_effect = OSError("release failed")
                try:
                    raise ValueError("already handled by caller")
                except ValueError:
                    with self.assertLogs("bd2_fishing.game.fishing", level="ERROR"):
                        with self.assertRaises(OSError):
                            run_observed_qte(strategy, Mock())
                strategy.catch_observer.finalize.assert_called_once_with("exception:OSError")

    def test_outer_cleanup_failure_still_runs_finalizer_without_trace_wrapper(self):
        strategy = Mock()
        strategy._stop_feedback.side_effect = OSError("release failed")
        with self.assertLogs("bd2_fishing.game.fishing", level="ERROR"):
            with self.assertRaises(OSError):
                run_observed_qte(strategy, Mock())
        strategy.catch_observer.finalize.assert_called_once_with("exception:OSError")
