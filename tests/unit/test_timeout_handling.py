"""超时现场分类、停止传播及反馈采样依据；全部使用离线帧和设备替身。"""

import configparser
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

import cv2
import numpy as np

from bd2_fishing.app.service import TaskController
from bd2_fishing.game.fishing import feedback, qte
from bd2_fishing.game.fishing.feedback_rules import OutcomeTracker
from bd2_fishing.game.fishing.settlement import CatchObserver, run_observed_qte
from bd2_fishing.game.fishing.tracing import QTEControlTimeout
from bd2_fishing.infrastructure import settings
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class TimeoutTests(unittest.TestCase):
    def setUp(self):
        self.config = configparser.ConfigParser()
        self.config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        self.config.set("recovery", "page_wait_seconds", "0")
        self.region = Rect(1, 460, 946, 992)
        root = Path(__file__).parents[1] / "fixtures" / "qte_control"
        self.active = cv2.imread(str(root / "u07_observer_control.png"))

    def strategy(self, cls=qte.FrostStraitQTEStrategy):
        strategy = cls(self.config, self.region)
        strategy._start_feedback = Mock()
        strategy.longest_keep_time = 0
        return strategy

    def test_both_deadlines_stop_without_input_and_save_same_control_frame(self):
        for cls in (qte.FrostStraitQTEStrategy, qte.AbyssMawQTEStrategy):
            with self.subTest(strategy=cls.__name__), tempfile.TemporaryDirectory() as directory:
                strategy = self.strategy(cls)
                observer = CatchObserver(Mock(), self.config, self.region)
                strategy.catch_observer = observer
                capture = Mock(grab=Mock(return_value=self.active))
                with (
                    patch(
                        "bd2_fishing.game.fishing.settlement.paths.get_base_path",
                        return_value=directory,
                    ),
                    patch.object(qte.pydirectinput, "press") as press,
                    patch.object(qte.pydirectinput, "click") as click,
                    patch.object(observer, "finish") as finish,
                    patch.object(observer, "inspect_current_page", return_value="unrecognized"),
                ):
                    with self.assertRaises(QTEControlTimeout):
                        run_observed_qte(strategy, capture)
                    press.assert_not_called()
                    click.assert_not_called()
                    finish.assert_not_called()
                capture.grab.assert_called_once_with(strategy.roi_pos)
                self.assertTrue(observer.save_done.wait(2))
                with ZipFile(next(Path(directory).rglob("*.zip"))) as archive:
                    metadata = json.loads(archive.read("metadata.json"))
                    frame = cv2.imdecode(
                        np.frombuffer(archive.read("timeout_control.png"), np.uint8), 1
                    )
                self.assertTrue(np.array_equal(frame, self.active))
                self.assertEqual(metadata["exit_reason"], "control_timeout")
                self.assertEqual(metadata["control_timeout"]["state"], "qte_active")
                self.assertEqual(metadata["result"]["status"], "unknown")

    def test_missing_frame_unknown_page_and_panel_never_trigger_blind_close(self):
        for frame, panel, expected in (
            (None, False, "capture_unavailable"),
            (np.zeros_like(self.active), False, "unrecognized_page"),
            (np.zeros_like(self.active), True, "settlement_visible"),
        ):
            with self.subTest(state=expected):
                strategy = self.strategy()
                observer = Mock(evidence_frames={}, evidence_metadata={"panel_open": panel})
                strategy.catch_observer = observer
                with patch.object(qte.pydirectinput, "click") as click:
                    with self.assertRaises(QTEControlTimeout):
                        strategy._on_control_timeout(Mock(grab=Mock(return_value=frame)))
                    click.assert_not_called()
                self.assertEqual(observer.evidence_metadata["control_timeout"]["state"], expected)
                self.assertEqual(observer.finish.call_count, 0 if frame is None else 1)

    def test_stop_before_inspection_never_captures_and_inspection_error_still_stops(self):
        strategy = self.strategy()
        camera = Mock(grab=Mock(side_effect=ValueError("camera")))
        with patch.object(control, "checkpoint", side_effect=control.RunStopped("stop")):
            with self.assertRaises(control.RunStopped):
                strategy._on_control_timeout(camera)
        camera.grab.assert_not_called()
        strategy.catch_observer = Mock(evidence_frames={}, evidence_metadata={})
        with self.assertRaises(QTEControlTimeout):
            strategy._on_control_timeout(camera)
        self.assertEqual(
            strategy.catch_observer.evidence_metadata["control_timeout"]["inspection_error"],
            "ValueError",
        )

    def test_task_releases_inputs_and_does_not_start_next_round(self):
        strategy = self.strategy()
        after = Mock()
        release = Mock()

        def target():
            run_observed_qte(strategy, Mock(grab=Mock(return_value=self.active)))
            after()

        task = TaskController(target, release)
        task.start()
        task.worker.join(3)
        self.assertFalse(task.running)
        self.assertIn("QTE 控制达到", task.last_error)
        after.assert_not_called()
        release.assert_called_once()

    def test_timeout_categories_distinguish_sampling_and_feedback_evidence(self):
        cases = (
            ([], "no_observation"),
            ([(0.1, None), (0.6, None)], "observation_gap"),
            ([(i / 10, None) for i in range(1, 8)], "feedback_not_detected"),
            ([(i / 10, "hit") for i in range(1, 8)], "feedback_not_renewed"),
        )
        for observations, category in cases:
            with self.subTest(category=category):
                tracker = OutcomeTracker()
                tracker.observe("hit", -0.1)
                tracker.begin(0)
                for stamp, label in observations:
                    self.assertEqual(tracker.observe(label, stamp, 0.9 if label else 0.2), [])
                (result,) = tracker.expire(0.8)
                self.assertEqual(result.result, "unknown")
                self.assertEqual(result.diagnostics["category"], category)
                self.assertEqual(result.diagnostics["frames"], len(observations))
                self.assertEqual(tracker.expire(1), [])

    def test_late_frame_cannot_rewrite_timeout_or_claim_continuous_observation(self):
        tracker = OutcomeTracker()
        tracker.begin(0)
        timeout, observed = tracker.observe("hit", 0.8, 0.95)
        self.assertEqual(timeout.diagnostics["category"], "no_observation")
        self.assertEqual(timeout.result, "unknown")
        self.assertIsNone(observed.attempt)
        self.assertEqual(observed.result, "hit")
        self.assertEqual(tracker.feedback_events[-1]["candidate_attempts"], [])
        tracker.begin(1)
        (expired,) = tracker.begin(2)
        self.assertEqual(expired.reason, "反馈等待超时")

    def test_observer_failure_is_reported_without_misattributing_later_input(self):
        session = feedback.FeedbackSession(self.config, self.region)
        session.begin_press()
        with (
            patch(
                "bd2_fishing.infrastructure.windows.gdi.FeedbackCapture",
                side_effect=ValueError("offline camera"),
            ),
            patch.object(feedback.window, "enable_dpi_awareness"),
            patch.object(feedback.window, "WindowGuard", return_value=lambda: None),
        ):
            session.run()
        self.assertEqual(session.reader_error, "ValueError")
        self.assertEqual(session.unknown_categories["observer_failed"], 1)
        session.begin_press()
        session.close()
        self.assertEqual(session.unknown_categories["observer_failed"], 2)
        self.assertEqual(session.counts["unknown"], 2)
