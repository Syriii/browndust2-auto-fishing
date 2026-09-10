"""独立场景取证：离线采集替身，禁止真实桌面截图和游戏输入。"""

import configparser
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

import cv2
import numpy as np

from bd2_fishing.game.fishing import feedback
from bd2_fishing.game.fishing.scene_evidence import SceneRecorder
from bd2_fishing.infrastructure import settings
from bd2_fishing.runtime.control import RunStopped
from bd2_fishing.runtime.geometry import Rect


class SceneEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.config = configparser.ConfigParser()
        self.config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        self.config.set("diagnostics", "qte_feedback_enabled", "false")
        self.window = Rect(1, 460, 946, 992)
        self.region = Rect(285, 800, 663, 955)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def recorder(self):
        return SceneRecorder(self.config, self.window, self.region, "round-test", self.temp.name)

    def frame(self, *, special=False):
        frame = np.zeros((155, 378, 3), np.uint8)
        root = Path(__file__).parents[1] / "fixtures" / "qte_control"
        raw = cv2.imread(
            str(root / ("f05_observer_control.png" if special else "u07_observer_control.png"))
        )
        if not special:
            # 真实计时器 + 合成普通黄蓝条，避免将加载状态作为普通 QTE 正例。
            hsv = np.zeros((19, 244, 3), np.uint8)
            hsv[:, 50:150] = (99, 230, 255)
            hsv[:, 80:110] = (25, 200, 255)
            hsv[:, 125] = (0, 0, 255)
            raw[21:40, 68:312] = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        frame[96:138, 18:330] = raw
        return frame

    def test_no_failure_or_press_required_and_old_debug_off_still_records(self):
        recorder = self.recorder()
        normal, special = self.frame(), self.frame(special=True)
        recorder.observe(normal, 1)
        recorder.observe(special, 1.1)
        recorder.observe(special, 1.2)
        recorder.observe(normal, 1.3)
        recorder.close([dict(result="critical", observed_at=1.25)], "finished")
        self.assertTrue(recorder.done.wait(3))
        (path,) = Path(self.temp.name).glob("candidates/*.zip")
        with ZipFile(path) as archive:
            metadata = json.loads(archive.read("metadata.json"))
            self.assertEqual(metadata["attempts"], [])
            self.assertEqual(metadata["feedback"][0]["result"], "critical")
            self.assertIn("multiple_pointer_candidates", metadata["candidates"][0]["candidates"])
            self.assertEqual(metadata["frames"][0]["captured_at_monotonic"], 1)
            self.assertEqual(metadata["frames"][-1]["captured_at_monotonic"], 1.3)
            restored = cv2.imdecode(
                np.frombuffer(archive.read(metadata["frames"][1]["file"]), np.uint8), 1
            )
            np.testing.assert_array_equal(restored, special)
        self.assertEqual(recorder.bytes, 0)

    def test_new_mechanism_inside_old_half_second_limit_is_saved_with_lifecycle(self):
        recorder = self.recorder()
        raw = self.frame()
        first = dict(
            roi_available=True,
            qte_active=True,
            qte_shape=[19, 244, 3],
            appearance_regions={"red_region": ((10, 20),)},
        )
        both = dict(
            first, appearance_regions={"red_region": ((10, 20),), "purple_region": ((50, 60),)}
        )
        recorder.signals.inspect = Mock(
            side_effect=[
                (("red_content",), dict(first)),
                (("red_content",), dict(first)),
                (("red_content", "purple_content"), dict(both)),
                (("red_content", "purple_content"), dict(both)),
                (("red_content",), dict(first)),
                (("red_content",), dict(first)),
            ]
        )
        for stamp in (1, 1.02, 1.04, 1.06, 1.08, 1.1):
            recorder.observe(raw, stamp)
        self.assertEqual([event["observed_at"] for event in recorder.events], [1.02, 1.06])
        recorder.press(3, 1.05, {"reason": "yellow_overlap"})
        with patch(
            "bd2_fishing.game.fishing.scene_evidence.bundle_writer.submit", return_value=True
        ) as submit:
            recorder.close([], "finished")
        metadata = submit.call_args.args[2]
        red, purple = metadata["appearance_lifecycle"]["instances"]
        self.assertEqual((red["state"], purple["state"]), ("unknown", "disappeared"))
        self.assertEqual(purple["attempts_in_observed_interval"], [3])
        self.assertEqual(purple["result"], "unknown")
        self.assertTrue(
            any(record["captured_at_monotonic"] == 1.1 for record in metadata["frames"])
        )

    def test_same_timestamp_does_not_confirm_an_event(self):
        recorder = self.recorder()
        for _ in range(3):
            recorder.observe(self.frame(special=True), 1)
        self.assertFalse(recorder.events)
        self.assertEqual(recorder.non_increasing_timestamps, 2)

    def test_ordinary_timeline_is_separate_and_buffer_is_owned(self):
        recorder = self.recorder()
        frame = self.frame()
        expected = frame.copy()
        recorder.observe(frame, 1)
        frame[:] = 0
        recorder.close([], "cancelled")
        self.assertTrue(recorder.done.wait(3))
        (path,) = Path(self.temp.name).glob("routine/*.zip")
        with ZipFile(path) as archive:
            metadata = json.loads(archive.read("metadata.json"))
            self.assertFalse(metadata["candidates"])
            restored = cv2.imdecode(np.frombuffer(archive.read("frame_000.png"), np.uint8), 1)
            np.testing.assert_array_equal(restored, expected)

    def test_real_color_candidates_do_not_confuse_normal_blue_glow(self):
        root = Path(__file__).parents[1] / "fixtures" / "qte_control"
        for name, expected in (
            ("red_teeth_4.png", "red_content"),
            ("purple_content.png", "purple_content"),
            ("u07_observer_control.png", "blue_without_yellow"),
            ("blue_only_0.png", "blue_without_yellow"),
        ):
            with self.subTest(name=name):
                frame = np.zeros((155, 378, 3), np.uint8)
                frame[96:138, 18:330] = cv2.imread(str(root / name))
                signals, _ = self.recorder().signals.inspect(frame)
                self.assertIn(expected, signals)
                self.assertNotIn("green_content", signals)
                if expected != "purple_content":
                    self.assertNotIn("purple_content", signals)
        green = self.frame()
        green[117:136, 140:180] = cv2.cvtColor(
            np.full((19, 40, 3), (60, 255, 255), np.uint8), cv2.COLOR_HSV2BGR
        )
        self.assertIn("green_content", self.recorder().signals.inspect(green)[0])

    def test_transient_and_loading_do_not_claim_special_mechanism(self):
        recorder = self.recorder()
        recorder.observe(self.frame(special=True), 0)
        recorder.observe(self.frame(), 0.1)
        recorder.observe(np.zeros((155, 378, 3), np.uint8), 0.2)
        recorder.observe(np.zeros((155, 378, 3), np.uint8), 0.3)
        self.assertFalse(recorder.events)
        # 两张相隔很久的异常帧不算连续确认。
        recorder.observe(self.frame(special=True), 1)
        recorder.observe(self.frame(special=True), 2)
        self.assertFalse(recorder.events)
        self.assertEqual(recorder.sample_gaps, 2)

    def test_memory_event_count_and_close_are_bounded(self):
        recorder = self.recorder()
        recorder.MAX_FRAMES = 5
        recorder.MAX_BYTES = self.frame().nbytes * 3
        special = self.frame(special=True)
        with patch(
            "bd2_fishing.game.fishing.scene_evidence.bundle_writer.submit", return_value=False
        ):
            for i in range(100):
                recorder.observe(special, i * 0.1)
        self.assertLessEqual(len(recorder.frames), 3)
        self.assertLessEqual(recorder.bytes, recorder.MAX_BYTES)
        self.assertGreater(recorder.dropped_frames, 0)
        self.assertLess(len(recorder.events), 6)
        with patch(
            "bd2_fishing.game.fishing.scene_evidence.bundle_writer.submit", return_value=False
        ) as submit:
            recorder.close([], "cancelled")
            recorder.observe(special, 11)
            recorder.press(99, 11, {})
            recorder.close([], "cancelled")
        submit.assert_called_once()
        self.assertFalse(recorder.submitted)
        self.assertFalse(recorder.frames)

    def test_first_candidate_survives_later_bursts_and_final_frame_is_retained(self):
        recorder = self.recorder()
        frame = self.frame(special=True)
        recorder.MAX_BYTES = frame.nbytes * 4
        with patch(
            "bd2_fishing.game.fishing.scene_evidence.bundle_writer.submit", return_value=True
        ) as submit:
            for i in range(101):
                recorder.observe(frame, i * 0.1)
            recorder.close([], "cancelled")
        metadata = submit.call_args.args[2]
        parts = [call.args[2] for call in submit.call_args_list]
        self.assertGreater(len(parts), 1)
        frames = [frame for part in parts for frame in part["frames"]]
        self.assertTrue(all(len(part["frames"]) <= 4 for part in parts))
        self.assertIn(0.1, [f["captured_at_monotonic"] for f in frames])
        self.assertEqual(frames[-1]["captured_at_monotonic"], 10)
        location = metadata["candidates"][0]["evidence_location"]
        self.assertIsNotNone(location)
        linked = parts[location["part"]]["frames"]
        self.assertTrue(
            any(f["file"] == location["file"] and f["captured_at_monotonic"] == 0.1 for f in linked)
        )
        self.assertTrue(metadata["final_part"])
        self.assertEqual(
            sum(metadata["dropped_frame_reasons"].values()), metadata["dropped_frames"]
        )

    def test_periodic_frame_cannot_evict_candidate_when_full(self):
        recorder = self.recorder()
        frame = self.frame()
        recorder.MAX_BYTES = frame.nbytes * 2
        recorder._keep((1, frame, {}), "first_candidate")
        recorder._keep((2, frame, {}), "candidate")
        with patch(
            "bd2_fishing.game.fishing.scene_evidence.bundle_writer.submit", return_value=False
        ):
            recorder._keep((3, frame, {}), "periodic")
        self.assertEqual(set(recorder.frames), {1, 2})
        self.assertEqual(recorder.drop_reasons["rejected_periodic"], 1)

    def test_healthy_rollover_preserves_every_selected_frame_and_caps_parts(self):
        recorder = self.recorder()
        recorder.MAX_FRAMES = 4
        frame = self.frame()
        with patch(
            "bd2_fishing.game.fishing.scene_evidence.bundle_writer.submit", return_value=True
        ) as submit:
            for i in range(20):
                recorder._keep((i * 0.02, frame.copy(), {}), "candidate")
            recorder.close([], "finished")
        parts = [call.args[2] for call in submit.call_args_list]
        self.assertEqual(len(parts), 5)
        self.assertEqual(len({part["scene_id"] for part in parts}), 1)
        stamps = [f["captured_at_monotonic"] for part in parts for f in part["frames"]]
        self.assertEqual(stamps, [i * 0.02 for i in range(20)])
        self.assertEqual(recorder.dropped_frames, 0)
        recorder = self.recorder()
        recorder.MAX_FRAMES, recorder.MAX_PARTS = 4, 3
        with patch(
            "bd2_fishing.game.fishing.scene_evidence.bundle_writer.submit", return_value=True
        ) as submit:
            for i in range(20):
                recorder._keep((i * 0.02, frame.copy(), {}), "candidate")
            recorder.close([], "finished")
        self.assertEqual(submit.call_count, 3)
        self.assertGreater(recorder.dropped_frames, 0)

    def test_multiple_parts_are_written_with_intact_pixels_and_final_marker(self):
        recorder = self.recorder()
        recorder.MAX_FRAMES = 4
        for index in range(8):
            recorder._keep((index * 0.02, np.full((12, 12, 3), index, np.uint8), {}), "periodic")
        recorder.close([], "finished")
        self.assertTrue(recorder.done.wait(3))
        parts = {}
        values = []
        for path in Path(self.temp.name).rglob("*.zip"):
            with ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                meta = json.loads(archive.read("metadata.json"))
                parts[meta["part"]] = meta
                for frame in meta["frames"]:
                    pixels = cv2.imdecode(np.frombuffer(archive.read(frame["file"]), np.uint8), 1)
                    self.assertTrue(np.all(pixels == pixels[0, 0, 0]))
                    values.append(int(pixels[0, 0, 0]))
        self.assertEqual(sorted(values), list(range(8)))
        self.assertEqual(set(parts), {0, 1})
        self.assertFalse(parts[0]["final_part"])
        self.assertTrue(parts[1]["final_part"])

    def test_adjacent_pointer_edges_are_retained_but_not_multiple_pointer_event(self):
        frame = self.frame()
        # 真实普通布局中的合成相邻亮线；仅约束外观取证，不修改光标定位。
        frame[117:136, 211] = frame[117:136, 212]
        frame[117:136, 210] = (255, 255, 255)
        frame[117:136, 214] = (220, 220, 220)
        signals, features = self.recorder().signals.inspect(frame)
        self.assertNotIn("multiple_pointer_candidates", signals)
        self.assertGreaterEqual(len(features["pointer_candidates"]), 2)

    def test_background_encoding_does_not_run_on_observer_thread(self):
        recorder = self.recorder()
        recorder.observe(self.frame(special=True), 0)
        recorder.observe(self.frame(special=True), 0.1)
        entered, release = threading.Event(), threading.Event()
        encode = cv2.imencode
        threads = []

        def delayed_encode(*args):
            threads.append(threading.current_thread().name)
            entered.set()
            release.wait(2)
            return encode(*args)

        with patch(
            "bd2_fishing.infrastructure.diagnostics.bundle_writer.cv2.imencode",
            side_effect=delayed_encode,
        ):
            try:
                recorder.close([], "finished")
                self.assertTrue(entered.wait(1))
                self.assertFalse(recorder.done.is_set())
            finally:
                release.set()
                self.assertTrue(recorder.done.wait(3))
        self.assertTrue(all(name == "evidence-writer" for name in threads))

    def test_production_observer_records_scene_without_any_input(self):
        session = feedback.FeedbackSession(self.config, self.window)
        session.scenes = self.recorder()
        camera = Mock()
        camera.grab.side_effect = [
            self.frame(special=True),
            self.frame(special=True),
            RunStopped("offline end"),
        ]
        capture = Mock()
        capture.__enter__ = Mock(return_value=camera)
        capture.__exit__ = Mock(return_value=False)
        session.matcher = Mock(detect=Mock(return_value=(None, 0)))
        with (
            patch("bd2_fishing.infrastructure.windows.gdi.FeedbackCapture", return_value=capture),
            patch.object(feedback.window, "enable_dpi_awareness"),
            patch.object(feedback.window, "WindowGuard", return_value=lambda: None),
            patch("bd2_fishing.infrastructure.windows.input.press") as press,
        ):
            session.run()
            session.close()
            press.assert_not_called()
        self.assertEqual(session.tracker.sequence, 0)
        self.assertTrue(session.scenes.submitted)
        self.assertTrue(list(Path(self.temp.name).glob("candidates/*.zip")))
