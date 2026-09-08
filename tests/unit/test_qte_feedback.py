"""真实 QTE 反馈图回归及单次归属测试；不打开相机、不发送游戏输入。"""

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
from bd2_fishing.game.fishing.feedback import select_evidence_frames
from bd2_fishing.game.fishing.feedback_rules import Outcome, OutcomeTracker
from bd2_fishing.game.fishing.recognition import FeedbackMatcher
from bd2_fishing.infrastructure import settings as settings
from bd2_fishing.infrastructure.diagnostics.qte_evidence import EvidenceWriter
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime import geometry as geometry
from tests.support import DEFAULT_CONFIG, ROOT

FIXTURES = ROOT / "tests/fixtures/qte_feedback"


class FeedbackImageTests(unittest.TestCase):
    def test_real_words_and_backgrounds(self):
        matcher = FeedbackMatcher(875, 492)
        verified = set()
        for sample in json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8")):
            with self.subTest(file=sample["file"]):
                frame = cv2.imdecode(
                    np.frombuffer((FIXTURES / sample["file"]).read_bytes(), np.uint8), 1
                )
                label, _ = matcher.detect(frame[:89])
                # 动画淡出或被特效覆盖的文字可保留未知，但不能错认另一种结果。
                self.assertIn(label, (None, sample["label"]))
                if label:
                    verified.add(label)
        self.assertEqual(verified, {"critical", "hit", "miss", "fail"})

    def test_real_negative_scene_cannot_be_forced_into_a_result(self):
        matcher = FeedbackMatcher(875, 492)
        for value in (0, 255):
            self.assertEqual(matcher.detect(np.full((89, 350, 3), value, np.uint8))[0], None)


class OutcomeTests(unittest.TestCase):
    def test_each_new_word_maps_to_actual_feedback_not_geometry(self):
        for label, expected in (
            ("critical", "critical"),
            ("hit", "hit"),
            ("miss", "miss"),
            ("fail", "miss"),
        ):
            with self.subTest(label=label):
                tracker = OutcomeTracker()
                self.assertEqual(tracker.begin(0), [])
                (result,) = tracker.observe(label, 0.1, 0.95)
                self.assertEqual(
                    (result.attempt, result.result, result.feedback), (1, expected, label)
                )
                self.assertEqual(tracker.close(0.5), [])

    def test_old_animation_cannot_confirm_second_press(self):
        t = OutcomeTracker()
        t.begin(0)
        self.assertEqual(t.observe("critical", 0.1)[0].result, "critical")
        t.begin(0.3)
        self.assertEqual(t.observe("critical", 0.35), [])
        self.assertEqual(t.observe("critical", 0.7), [])  # 无图时间间隔不能让旧动画重新生效
        self.assertEqual(t.close(0.9)[0].result, "unknown")

    def test_blank_interval_rearms_same_word(self):
        t = OutcomeTracker()
        t.begin(0)
        t.observe("hit", 0.1)
        t.observe(None, 0.25)
        t.observe(None, 0.4)
        t.begin(0.5)
        self.assertEqual(t.observe("hit", 0.6)[0].attempt, 2)

    def test_single_bad_frame_does_not_duplicate_animation(self):
        t = OutcomeTracker()
        t.begin(0)
        t.observe("hit", 0.1)
        t.observe(None, 0.12)
        t.begin(0.13)
        self.assertEqual(t.observe("hit", 0.14), [])

    def test_bad_frame_followed_by_capture_gap_cannot_rearm_animation(self):
        t = OutcomeTracker()
        t.begin(0)
        t.observe("hit", 0.1)
        t.observe(None, 0.12)
        t.begin(0.3)
        self.assertEqual(t.observe("hit", 0.4), [])
        self.assertEqual(t.close(0.5)[0].result, "unknown")

    def test_timeout_without_images_does_not_count_as_blank(self):
        t = OutcomeTracker()
        t.begin(0)
        t.observe("critical", 0.1)
        t.begin(0.3)
        self.assertEqual(t.expire(1.1)[0].result, "unknown")
        self.assertEqual(t.expire(1.2), [])
        t.begin(1.3)
        self.assertEqual(t.observe("critical", 1.4), [])
        self.assertEqual(t.close(1.5)[0].result, "unknown")

    def test_rapid_unconfirmed_presses_remain_ambiguous(self):
        t = OutcomeTracker()
        t.begin(0)
        self.assertEqual(t.begin(0.3)[0].result, "unknown")
        (result,) = t.observe("critical", 0.4)
        self.assertEqual((result.attempt, result.result), (2, "unknown"))
        self.assertIn("归属不明确", result.reason)

    def test_confirmed_game_feedback_is_retained_even_when_press_is_ambiguous(self):
        t = OutcomeTracker()
        t.begin(0)
        t.begin(0.3)
        self.assertEqual(t.observe("hit", 0.4)[0].result, "unknown")
        self.assertEqual(t.feedback_events[0]["result"], "hit")
        self.assertEqual(t.feedback_events[0]["candidate_attempts"], [1, 2])
        t.observe("hit", 0.45)
        self.assertEqual(len(t.feedback_events), 1)

    def test_expired_old_candidate_does_not_hide_new_hit(self):
        t = OutcomeTracker()
        t.begin(0)
        t.begin(0.7)
        (result,) = t.observe("hit", 0.78)
        self.assertEqual((result.attempt, result.result), (2, "hit"))
        self.assertEqual(t.feedback_events[0]["candidate_attempts"], [2])

    def test_timeout_is_unknown_not_a_miss(self):
        t = OutcomeTracker()
        t.begin(0)
        (result,) = t.observe(None, 0.8)
        self.assertEqual(result.result, "unknown")
        self.assertEqual(t.close(1), [])

    def test_feedback_captured_before_press_cannot_confirm_it(self):
        t = OutcomeTracker()
        t.begin(1)
        self.assertEqual(t.observe("critical", 0.99), [])
        self.assertEqual(t.observe("critical", 1.05), [])
        self.assertEqual(t.close(1.3)[0].result, "unknown")

    def test_unassigned_fail_keeps_evidence_without_inventing_a_press(self):
        (result,) = OutcomeTracker().observe("fail", 1)
        self.assertIsNone(result.attempt)
        self.assertEqual(result.result, "miss")


class IntegrationTests(unittest.TestCase):
    def config(self):
        config = configparser.ConfigParser()
        config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        return config

    def test_old_debug_switch_cannot_disable_evidence_or_change_input(self):
        config = self.config()
        config.set("diagnostics", "qte_feedback_enabled", "false")
        strategy = qte_strategy.FrostStraitQTEStrategy(config, geometry.Rect(0, 0, 875, 492))
        self.assertTrue(strategy.feedback_enabled)
        with patch("bd2_fishing.game.fishing.feedback.FeedbackSession") as session:
            strategy._start_feedback()
            session.return_value.start.assert_called_once_with()
        observer = Mock()
        strategy._feedback_session = observer
        with patch.object(qte_strategy.pydirectinput, "press", return_value=True) as press:
            self.assertTrue(strategy._press_qte())
        observer.begin_press.assert_called_once_with()
        press.assert_called_once_with("space")

    def test_source_config_and_defaults_enable_observer_consistently(self):
        source = configparser.ConfigParser()
        source.read(DEFAULT_CONFIG, encoding="utf-8-sig")
        self.assertEqual(source.getint("diagnostics", "failure_max_events"), 100)
        self.assertEqual(self.config().getint("diagnostics", "failure_max_events"), 100)
        source.remove_option("diagnostics", "qte_feedback_enabled")
        self.assertTrue(
            qte_strategy.FrostStraitQTEStrategy(
                source, geometry.Rect(0, 0, 875, 492)
            ).feedback_enabled
        )

    def test_observer_is_closed_once_when_qte_ends(self):
        strategy = qte_strategy.FrostStraitQTEStrategy(self.config(), geometry.Rect(0, 0, 875, 492))
        observer = Mock()
        strategy._feedback_session = observer
        strategy._stop_feedback()
        strategy._stop_feedback()
        observer.close.assert_called_once_with()
        self.assertIsNone(strategy._feedback_session)

    def test_observer_error_does_not_suppress_input(self):
        strategy = qte_strategy.FrostStraitQTEStrategy(self.config(), geometry.Rect(0, 0, 875, 492))
        strategy._feedback_session = Mock(
            begin_press=Mock(side_effect=ValueError("diagnostic error"))
        )
        with (
            patch.object(qte_strategy.pydirectinput, "press") as press,
            self.assertLogs("bd2_fishing.game.fishing.qte", level="ERROR"),
        ):
            strategy._press_qte()
        press.assert_called_once_with("space")

    def test_input_stop_still_propagates(self):
        strategy = qte_strategy.FrostStraitQTEStrategy(self.config(), geometry.Rect(0, 0, 875, 492))
        with patch.object(
            qte_strategy.pydirectinput, "press", side_effect=run_control.RunStopped("stop")
        ):
            with self.assertRaises(run_control.RunStopped):
                strategy._press_qte()

    def test_evidence_contains_same_frame_masks_and_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = EvidenceWriter(
                directory,
                self.config(),
                geometry.Rect(262, 315, 612, 458),
                geometry.Rect(0, 0, 875, 492),
            )
            frame = cv2.imdecode(np.frombuffer((FIXTURES / "miss.png").read_bytes(), np.uint8), 1)
            writer.submit(
                Outcome(1, 1, 1.1, "miss", "miss", "实图反馈", 0.95), [(0.95, frame), (1.1, frame)]
            )
            writer.close()
            self.assertFalse(writer.thread.is_alive())
            (archive,) = Path(directory).glob("*.zip")
            with ZipFile(archive) as z:
                self.assertIsNone(z.testzip())
                metadata = json.loads(z.read("metadata.json"))
                self.assertEqual(metadata["outcome"]["result"], "miss")
                self.assertEqual(metadata["evidence_region"], [262, 315, 612, 458])
                self.assertAlmostEqual(metadata["frames"][0]["relative_to_press_ms"], -50)
                original = cv2.imdecode(np.frombuffer(z.read("frame_00.png"), np.uint8), 1)
                np.testing.assert_array_equal(original, frame)
                for color in ("white", "yellow", "blue"):
                    self.assertIn(f"frame_00_{color}.png", z.namelist())

    def test_evidence_keeps_feedback_and_press_neighbors_when_downsampling(self):
        frames = [(i * 0.02, None) for i in range(40)]
        outcome = Outcome(1, 0.215, 0.54, "miss", "fail", "test")
        selected = select_evidence_frames(frames, outcome)
        stamps = [stamp for stamp, _ in selected]
        self.assertLessEqual(len(selected), 8)
        for stamp in (0, 0.20, 0.22, 0.54, 0.78):
            self.assertIn(stamp, stamps)
        self.assertEqual(stamps, sorted(set(stamps)))


if __name__ == "__main__":
    unittest.main()
