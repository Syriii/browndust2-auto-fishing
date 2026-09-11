"""决策截图与按键、反馈关联；全部使用离线帧，禁止真实游戏输入。"""

import configparser
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

import cv2
import numpy as np

from bd2_fishing.game.fishing import qte as qte_strategy
from bd2_fishing.game.fishing.feedback import FeedbackSession
from bd2_fishing.infrastructure import settings as settings
from bd2_fishing.infrastructure.diagnostics.qte_evidence import EvidenceWriter
from bd2_fishing.perception import image as vision
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime import geometry as geometry


class DecisionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.config = configparser.ConfigParser()
        self.config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        self.window = geometry.Rect(0, 0, 875, 492)

    def test_control_frame_survives_buffer_reuse_and_is_distinct_from_feedback_frame(self):
        observer = Mock(round_id="decision-round", attempt_outcomes=[], game_feedback=[])
        session = FeedbackSession(self.config, self.window, observer)
        control = np.full((30, 80, 3), (0, 255, 255), np.uint8)
        expected = control.copy()
        feedback = np.full((143, 350, 3), 27, np.uint8)
        decision = dict(
            reason="yellow_overlap",
            captured_at_monotonic=9.9,
            frame_region=[300, 400, 380, 430],
            cursor_x=10,
        )
        with tempfile.TemporaryDirectory() as directory:
            session.writer = EvidenceWriter(
                directory, self.config, session.region, self.window, round_id=session.round_id
            )
            with patch("bd2_fishing.game.fishing.feedback.time.monotonic", return_value=10):
                session.begin_press(decision, control)
            control[:] = 0
            decision["reason"] = "changed_after_call"
            session._drain_presses()
            session.samples.append((10.1, feedback))
            session.publish(session.tracker.observe("miss", 10.1, 0.95))
            session.close()
            with ZipFile(next(Path(directory).glob("*.zip"))) as archive:
                data = json.loads(archive.read("metadata.json"))
                self.assertIsNone(archive.testzip())
                self.assertEqual(data["round_id"], "decision-round")
                self.assertEqual(data["outcome"]["attempt"], 1)
                self.assertEqual(data["outcome"]["decision"]["reason"], "yellow_overlap")
                self.assertEqual(data["decision_frame"]["frame_region"], [300, 400, 380, 430])
                self.assertEqual(data["decision_frame"]["captured_at_monotonic"], 9.9)

                def decode(name, flag=1):
                    return cv2.imdecode(np.frombuffer(archive.read(name), np.uint8), flag)

                np.testing.assert_array_equal(decode("decision.png"), expected)
                np.testing.assert_array_equal(decode("frame_00.png"), feedback)
                hsv = cv2.cvtColor(expected, cv2.COLOR_BGR2HSV)
                for name in ("white", "yellow", "blue"):
                    color = vision.read_hsv_range(self.config, "roi", name)
                    np.testing.assert_array_equal(
                        decode(f"decision_{name}.png", 0),
                        cv2.inRange(hsv, color.lower, color.upper),
                    )
        self.assertEqual(observer.attempt_outcomes[0]["decision"]["cursor_x"], 10)
        self.assertFalse(session.press_decisions)
        self.assertFalse(session.pending_evidence)

    def test_unknown_on_stop_keeps_decision_even_without_observation_frames(self):
        session = FeedbackSession(self.config, self.window)
        with tempfile.TemporaryDirectory() as directory:
            session.writer = EvidenceWriter(directory, self.config, session.region, self.window)
            session.begin_press(dict(reason="no_cursor_fallback"), np.zeros((15, 50, 3), np.uint8))
            session.close()
            with ZipFile(next(Path(directory).glob("*.zip"))) as archive:
                data = json.loads(archive.read("metadata.json"))
                self.assertEqual(data["frames"], [])
                self.assertTrue(data["decision_frame_available"])
                self.assertEqual(data["outcome"]["result"], "unknown")
                self.assertEqual(data["outcome"]["decision"]["reason"], "no_cursor_fallback")

    def test_rapid_attempts_keep_their_own_decisions_and_unassigned_fail_gets_none(self):
        observer = Mock(round_id="round", attempt_outcomes=[], game_feedback=[])
        session = FeedbackSession(self.config, self.window, observer)
        session.writer = Mock()
        for stamp, reason in ((10, "yellow_overlap"), (10.2, "blue_fallback")):
            with patch("bd2_fishing.game.fishing.feedback.time.monotonic", return_value=stamp):
                session.begin_press(
                    dict(reason=reason), np.full((4, 5, 3), int(stamp * 10), np.uint8)
                )
        session._drain_presses()
        session.publish(session.tracker.observe("hit", 10.3, 0.95))
        session.samples.append((11, np.zeros((4, 5, 3), np.uint8)))
        session.publish(session.tracker.observe("fail", 11, 0.95))
        session.flush_evidence(12, force=True)
        records = observer.attempt_outcomes
        self.assertEqual([r["result"] for r in records], ["unknown", "unknown", "unknown"])
        self.assertEqual(
            [r["decision"]["reason"] for r in records[:2]], ["yellow_overlap", "blue_fallback"]
        )
        self.assertIsNone(records[2]["decision"])
        self.assertIsNone(records[2]["attempt"])
        calls = session.writer.submit.call_args_list
        self.assertEqual([int(call.args[2][0, 0, 0]) for call in calls[:2]], [100, 102])
        self.assertIsNone(calls[2].args[2])
        self.assertFalse(session.press_decisions)
        session.close()

    def test_confirmed_hit_releases_frame_but_retains_decision_metadata(self):
        observer = Mock(round_id="round", attempt_outcomes=[], game_feedback=[])
        session = FeedbackSession(self.config, self.window, observer)
        with patch("bd2_fishing.game.fishing.feedback.time.monotonic", return_value=10):
            session.begin_press(dict(reason="yellow_overlap"), np.zeros((4, 5, 3), np.uint8))
        session._drain_presses()
        session.publish(session.tracker.observe("critical", 10.1, 0.95))
        self.assertFalse(session.press_decisions)
        self.assertFalse(session.pending_evidence)
        self.assertEqual(observer.attempt_outcomes[0]["decision"]["reason"], "yellow_overlap")
        session.close()

    def test_all_existing_press_branches_and_no_press_keep_input_behavior(self):
        cases = [
            (qte_strategy.FrostStraitQTEStrategy, reason)
            for reason in ("yellow_overlap", "no_cursor_fallback", "red_obstruction", "no_press")
        ]
        cases += [
            (qte_strategy.AbyssMawQTEStrategy, reason)
            for reason in ("yellow_overlap", "blue_fallback", "no_press")
        ]
        for cls, reason in cases:
            for enabled in (False, True):
                with self.subTest(strategy=cls.__name__, reason=reason, enabled=enabled):
                    strategy = cls(self.config, self.window)
                    observer = Mock()
                    strategy._start_feedback = lambda: setattr(
                        strategy, "_feedback_session", observer if enabled else None
                    )
                    strategy._sleep_loop = Mock(side_effect=run_control.RunStopped("end sample"))
                    if reason == "blue_fallback":
                        strategy._sleep_loop = Mock(
                            side_effect=[None, run_control.RunStopped("end sample")]
                        )
                    raw = np.full(
                        (strategy.roi_pos.height, strategy.roi_pos.width, 3), 80, np.uint8
                    )
                    camera = Mock(grab=Mock(return_value=raw))
                    hsv = np.zeros((30, 300, 3), np.uint8)
                    if reason == "red_obstruction":
                        hsv[:] = strategy.red_range.lower
                    strategy._split_roi_and_time = Mock(return_value=(hsv, hsv))
                    strategy._time_bar_visible_from_masks = Mock(return_value=True)
                    cursor = np.zeros((30, 300), np.uint8)
                    if reason != "no_cursor_fallback":
                        cursor[:, 50] = 255
                    strategy._cursor_mask = Mock(return_value=cursor)
                    strategy._find_cursor_x = Mock(
                        return_value=None if reason == "no_cursor_fallback" else 50
                    )
                    target = np.zeros_like(cursor)
                    if reason == "yellow_overlap":
                        target[:, 40:80] = 255
                    strategy._yellow_mask = Mock(return_value=target)
                    strategy._yellow_source_mask = target
                    if cls is qte_strategy.AbyssMawQTEStrategy:
                        blue_target = np.zeros_like(cursor)
                        blue_target[:, 40:80] = 255
                        strategy._blue_mask = Mock(
                            return_value=blue_target
                            if reason == "blue_fallback"
                            else np.zeros_like(cursor)
                        )
                        strategy._blocker_detector.read = Mock(return_value=None)
                    with (
                        patch.object(qte_strategy.pydirectinput, "press") as press,
                        patch("bd2_fishing.runtime.control.sleep"),
                    ):
                        with self.assertRaises(run_control.RunStopped):
                            strategy.play_qte(camera)
                    if reason in ("no_press", "no_cursor_fallback", "red_obstruction"):
                        press.assert_not_called()
                        observer.begin_press.assert_not_called()
                    else:
                        press.assert_called_once_with("space")
                        if enabled:
                            metadata, frame = observer.begin_press.call_args.args
                            self.assertEqual(metadata["reason"], reason)
                            self.assertEqual(metadata["stage"], "before_input_call")
                            self.assertEqual(metadata["frame_region"], strategy.roi_pos.as_tuple())
                            np.testing.assert_array_equal(frame, raw)
                        else:
                            observer.begin_press.assert_not_called()
                    self.assertEqual(camera.grab.call_count, 2 if reason == "blue_fallback" else 1)
                    camera.grab.assert_called_with(strategy.roi_pos)
                    self.assertIsNone(strategy._decision_frame)


if __name__ == "__main__":
    unittest.main()
