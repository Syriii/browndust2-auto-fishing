"""慢日志、迟到识别与关闭竞争；只使用离线截图和替代输入。"""

import configparser
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import numpy as np

from bd2_fishing.game.fishing import feedback, qte
from bd2_fishing.game.fishing.settlement import CatchObserver
from bd2_fishing.infrastructure import settings
from bd2_fishing.infrastructure.diagnostics.qte_evidence import EvidenceWriter
from bd2_fishing.infrastructure.windows import gdi
from bd2_fishing.perception.ocr_types import OCRText
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class FeedbackLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.config = configparser.ConfigParser()
        self.config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        self.region = Rect(0, 0, 875, 492)
        self.frame = np.zeros((143, 350, 3), np.uint8)

    def capture_patches(self, stack):
        capture = Mock()
        capture.__enter__ = Mock(return_value=capture)
        capture.__exit__ = Mock(return_value=False)
        capture.grab.return_value = self.frame
        stack.enter_context(patch.object(gdi, "FeedbackCapture", return_value=capture))
        stack.enter_context(patch.object(feedback.window, "WindowGuard", return_value=Mock()))
        stack.enter_context(patch.object(feedback.window, "enable_dpi_awareness"))
        return capture

    def test_slow_feedback_log_cannot_delay_input_or_cancellation(self):
        entered, release, finished = (threading.Event() for _ in range(3))
        session = feedback.FeedbackSession(self.config, self.region)
        session.writer = Mock()
        session.matcher = Mock(detect=Mock(return_value=("hit", 0.99)))

        def slow_log(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test log gate timed out")

        session.log = Mock(log=slow_log)
        strategy = qte.FrostStraitQTEStrategy(self.config, self.region)
        strategy._feedback_session = session
        task_control = control.RunControl()
        cancelled = []

        def press_twice():
            try:
                with control.use_control(task_control):
                    strategy._press_qte()
                    task_control.stopped.set()
                    strategy._press_qte()
            except control.RunStopped:
                cancelled.append(True)
            finally:
                finished.set()

        with ExitStack() as stack:
            self.capture_patches(stack)
            raw = stack.enter_context(patch.object(qte.pydirectinput._input, "press"))
            session.thread = threading.Thread(target=session.run, daemon=True)
            session.thread.start()
            caller = threading.Thread(target=press_twice, daemon=True)
            try:
                self.assertTrue(entered.wait(2))
                caller.start()
                # 使用事件确认已完成，不把此上限当成性能达标线。
                self.assertTrue(finished.wait(1))
                self.assertTrue(cancelled)
                raw.assert_called_once_with("space")
            finally:
                session.done.set()
                release.set()
                if caller.ident is not None:
                    caller.join(2)
                session.thread.join(2)
                session.close()

    def test_close_seals_ledger_before_delayed_matcher_returns(self):
        entered, release = threading.Event(), threading.Event()
        observer = CatchObserver(Mock(), self.config, self.region)
        session = feedback.FeedbackSession(self.config, self.region, observer)
        session.writer = Mock()
        session.begin_press(dict(reason="test"), self.frame)

        def delayed_detect(frame):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test matcher gate timed out")
            return "miss", 0.99

        session.matcher = Mock(detect=delayed_detect)
        with ExitStack() as stack:
            capture = self.capture_patches(stack)
            session.thread = threading.Thread(target=session.run, daemon=True)
            session.thread.start()
            try:
                self.assertTrue(entered.wait(2))
                session.close()
                self.assertTrue(session.thread.is_alive())
                self.assertTrue(observer.feedback_diagnostics["reader_still_running"])
                self.assertFalse(session.begin_press())
                self.assertEqual(observer.attempt_outcomes[0]["result"], "unknown")
                before = list(observer.attempt_outcomes)
                calls = session.writer.submit.call_count
            finally:
                release.set()
                session.thread.join(2)
            self.assertFalse(session.thread.is_alive())
            self.assertEqual(observer.game_feedback, [])
            self.assertEqual(observer.attempt_outcomes, before)
            self.assertFalse(session.pending_evidence)
            self.assertEqual(session.writer.submit.call_count, calls)
            capture.__exit__.assert_called_once()
            session.close()
            session.writer.close.assert_called_once()

    def test_timer_ocr_returning_after_stop_cannot_change_snapshot(self):
        entered, release = threading.Event(), threading.Event()

        def recognize(frame):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test OCR gate timed out")
            return OCRText("1", 0.99)

        observer = CatchObserver(Mock(recognize=recognize), self.config, self.region)
        worker = threading.Thread(target=observer.observe_timer, args=(self.frame, 1), daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            observer.stop_observing()
            frame_at_stop = observer.last_frame
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(observer.readings)
        self.assertIs(observer.last_frame, frame_at_stop)
        observer.observe_timer(self.frame, 2)
        self.assertEqual(observer.last_frame_at, 1)

    def test_wait_for_busy_timer_ocr_remains_cancellable(self):
        observer = CatchObserver(Mock(), self.config, self.region)
        task_control = control.RunControl()
        task_control.stopped.set()
        with observer.ocr_lock, control.use_control(task_control):
            with self.assertRaises(control.RunStopped), observer._settlement_ocr():
                self.fail("must not enter OCR after stop")

    def test_press_queue_is_bounded_and_overload_cannot_claim_a_hit(self):
        observer = CatchObserver(Mock(), self.config, self.region)
        session = feedback.FeedbackSession(self.config, self.region, observer)
        session.log = Mock()
        for _ in range(session.presses.maxsize):
            self.assertTrue(session.begin_press())
        self.assertFalse(session.begin_press())
        self.assertEqual(session.presses.qsize(), 128)
        session._drain_presses()
        session.publish(session.tracker.observe("hit", 1e12, 0.99))
        session.close()
        attempts = [item for item in observer.attempt_outcomes if item["attempt"] is not None]
        self.assertEqual(len(attempts), 128)
        self.assertTrue(all(item["result"] == "unknown" for item in attempts))
        self.assertEqual(observer.feedback_diagnostics["dropped_press_records"], 1)

    def test_writer_rejects_jobs_after_close(self):
        with patch.object(EvidenceWriter, "save") as save:
            writer = EvidenceWriter("unused", self.config, self.region, self.region)
            writer.close()
            self.assertFalse(writer.submit(Mock(), []))
            self.assertTrue(writer.queue.empty())
            save.assert_not_called()

    def test_close_waits_outside_lock_and_scene_failure_still_seals_observer(self):
        observer = CatchObserver(Mock(), self.config, self.region)
        session = feedback.FeedbackSession(self.config, self.region, observer)
        session.log = Mock()
        session.scenes = Mock(submitted=False)
        session.scenes.close.side_effect = RuntimeError("writer unavailable")
        session.writer = Mock()
        session.thread = Mock(is_alive=Mock(return_value=False))
        session.begin_press()

        def join(*, timeout):
            self.assertEqual(timeout, 2)
            self.assertTrue(session.done.is_set())
            self.assertTrue(session.closed)
            acquired = session.lock.acquire(blocking=False)
            self.assertTrue(acquired, "joining while holding observation lock can deadlock")
            if acquired:
                session.lock.release()
            self.assertEqual(observer.attempt_outcomes[0]["result"], "unknown")

        session.thread.join.side_effect = join
        session.close()
        session.close()
        session.thread.join.assert_called_once()
        session.writer.close.assert_called_once()
        self.assertFalse(observer.feedback_diagnostics["reader_still_running"])
