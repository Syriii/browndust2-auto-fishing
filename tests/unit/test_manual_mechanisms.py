import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile

import cv2
import numpy as np

from bd2_fishing.runtime.control import RunStopped
from bd2_fishing.runtime.geometry import Rect
from scripts.checks import record_manual_mechanisms as manual


class ManualMechanismTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "recording"
        self.stop = Path(directory.name) / "stop"
        self.region = Rect(0, 0, 20, 10)
        self.frame = np.full((10, 20, 3), (32, 100, 200), dtype=np.uint8)
        self.capture = Mock()
        self.capture.__enter__ = Mock(return_value=self.capture)
        self.capture.__exit__ = Mock(return_value=False)
        self.capture.grab.side_effect = self.grab_and_stop
        self.addCleanup(patch.stopall)
        patch.object(manual, "FeedbackCapture", return_value=self.capture).start()
        patch.object(manual, "space_reader", return_value=Mock(side_effect=[True, False])).start()

    def grab_and_stop(self):
        self.stop.touch()
        return self.frame

    def run_recording(self, guard):
        return manual.record(
            self.output, self.region, guard, seconds=1, fps=60, stop_file=self.stop
        )

    def test_manual_frame_and_sampled_key_transition_round_trip(self):
        metadata = self.run_recording(Mock())
        self.assertEqual(metadata["stop_reason"], "stop_file")
        self.assertEqual(metadata["unsaved"], 0)
        sample = metadata["frames"][0]
        self.assertTrue(sample["space_before"])
        self.assertFalse(sample["space_after"])
        self.assertLessEqual(sample["before"], sample["after"])
        with ZipFile(self.output / "frames.zip") as archive:
            decoded = cv2.imdecode(np.frombuffer(archive.read(sample["file"]), np.uint8), 1)
        np.testing.assert_array_equal(decoded, self.frame)
        self.capture.__exit__.assert_called_once()

    def test_focus_loss_during_grab_discards_frame_and_preserves_stop_reason(self):
        guard = Mock(side_effect=[None, None, RunStopped("失焦")])
        with self.assertRaises(RunStopped):
            self.run_recording(guard)
        metadata = json.loads((self.output / "metadata.json").read_text("utf-8"))
        self.assertEqual(metadata["frames"], [])
        self.assertIn("失焦", metadata["stop_reason"])
        with ZipFile(self.output / "frames.zip") as archive:
            self.assertEqual(archive.namelist(), [])
        self.capture.__exit__.assert_called_once()

    def test_initial_guard_failure_does_not_open_capture_or_create_output(self):
        with self.assertRaises(RunStopped):
            self.run_recording(Mock(side_effect=RunStopped("锁屏")))
        self.assertFalse(self.output.exists())
        manual.FeedbackCapture.assert_not_called()

    def test_writer_error_is_reported_and_capture_is_closed(self):
        with patch.object(manual.cv2, "imencode", side_effect=OSError("disk test")):
            with self.assertRaisesRegex(RuntimeError, "写盘失败"):
                self.run_recording(Mock())
        metadata = json.loads((self.output / "metadata.json").read_text("utf-8"))
        self.assertEqual(metadata["stop_reason"], "writer_error")
        self.assertEqual(metadata["unsaved"], 1)
        self.assertIn("disk test", metadata["writer_error"])
        self.capture.__exit__.assert_called_once()

    def test_byte_limit_keeps_valid_archive_without_partial_frame(self):
        self.output.mkdir()
        writer = manual.ManualArchive(self.output, byte_limit=1024)
        writer.offer(self.frame, {"sequence": 0})
        writer.close()
        self.assertEqual(writer.reason, "byte_limit")
        self.assertEqual(writer.frames, [])
        with ZipFile(self.output / "frames.zip") as archive:
            self.assertEqual(archive.namelist(), [])
        self.assertLessEqual((self.output / "frames.zip").stat().st_size, 1024)

    def test_invalid_duration_rejected_before_window_or_storage(self):
        guard = Mock()
        for seconds in (float("nan"), float("inf"), 0, -1, 301):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                manual.record(self.output, self.region, guard, seconds=seconds, fps=30)
        guard.assert_not_called()
        self.assertFalse(self.output.exists())
