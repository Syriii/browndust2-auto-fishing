"""正常运行取证：关闭调试、跨线程错误、磁盘延迟和停止保护。"""

import json
import logging
import os
import tempfile
import threading
import traceback
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

import cv2
import numpy as np

from bd2_fishing.app.fishing_task import FishingBot
from bd2_fishing.game.fishing.settlement import CatchObserver, CatchResult
from bd2_fishing.infrastructure import settings
from bd2_fishing.infrastructure.diagnostics import incidents
from bd2_fishing.infrastructure.diagnostics.retention import prune_evidence
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class IncidentTests(unittest.TestCase):
    def test_capacity_limit_keeps_latest_even_if_single_bundle_is_large(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for number in range(3):
                path = root / f"{number}.zip"
                path.write_bytes(b"x" * 8)
                os.utime(path, (number + 1, number + 1))
            prune_evidence(root, 100, max_bytes=12)
            self.assertEqual([path.name for path in root.glob("*.zip")], ["2.zip"])
            prune_evidence(root, 100, max_bytes=1)
            self.assertTrue((root / "2.zip").exists())

    def test_background_error_saves_owned_frame_and_traceback_without_debug(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = np.full((10, 12, 3), 73, np.uint8)
            with incidents.recording_session(directory=directory):
                incidents.observe(frame, Rect(0, 0, 12, 10))
                frame[:] = 0

                def fail():
                    try:
                        raise ValueError("unexpected mechanism")
                    except ValueError:
                        logging.getLogger("bd2_fishing.game.test").exception("observer failed")

                thread = threading.Thread(target=fail)
                thread.start()
                thread.join(2)
            (file,) = Path(directory).glob("*.zip")
            with ZipFile(file) as archive:
                metadata = json.loads(archive.read("metadata.json"))
                saved = cv2.imdecode(np.frombuffer(archive.read("cached_00.png"), np.uint8), 1)
            self.assertTrue((saved == 73).all())
            self.assertIn("ValueError", metadata["details"]["traceback"])
            self.assertEqual(metadata["frames"][0]["region"], [0, 0, 12, 10])
            self.assertIsNone(incidents._active)

    def test_no_frame_is_explicit_and_restart_does_not_reuse_previous_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            with incidents.recording_session(directory=directory):
                incidents.observe(np.zeros((2, 2, 3), np.uint8), Rect(0, 0, 2, 2))
            with incidents.recording_session(directory=directory):
                incidents.report("initialization_failure")
            with ZipFile(next(Path(directory).glob("*.zip"))) as archive:
                metadata = json.loads(archive.read("metadata.json"))
                self.assertEqual(archive.namelist(), ["metadata.json"])
            self.assertFalse(metadata["screenshots_available"])

    def test_exception_formatting_runs_in_writer_thread(self):
        names = []
        real_format = traceback.format_exception

        def record_thread(*args):
            names.append(threading.current_thread().name)
            return real_format(*args)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "bd2_fishing.infrastructure.diagnostics.bundle_writer.traceback.format_exception",
                side_effect=record_thread,
            ),
        ):
            with incidents.recording_session(directory=directory) as recorder:
                try:
                    raise ValueError("background trace")
                except ValueError:
                    import sys

                    recorder.report("failure", exception_info=sys.exc_info())
            self.assertEqual(names, ["evidence-writer"])

    def test_slow_encoding_does_not_block_event_submission(self):
        started, release = threading.Event(), threading.Event()
        encode = cv2.imencode

        def slow(*args):
            started.set()
            if not release.wait(5):
                raise TimeoutError("test writer not released")
            return encode(*args)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(cv2, "imencode", side_effect=slow),
        ):
            with incidents.recording_session(directory=directory) as recorder:
                try:
                    incidents.observe(np.zeros((2, 2, 3), np.uint8), Rect(0, 0, 2, 2))
                    incidents.report("failure")
                    self.assertTrue(started.wait(2))
                    self.assertFalse(recorder.pending[0].is_set())
                finally:
                    release.set()

    def test_retention_survives_restart_and_preserves_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "notes.txt").write_text("keep")
            for number in range(4):
                with incidents.recording_session(directory=directory, max_events=2):
                    incidents.report("failure", number=number)
            records = []
            for file in Path(directory).glob("*.zip"):
                with ZipFile(file) as archive:
                    records.append(json.loads(archive.read("metadata.json"))["details"]["number"])
            self.assertEqual(sorted(records), [2, 3])
            self.assertEqual((Path(directory) / "notes.txt").read_text(), "keep")

    def test_guard_stop_does_not_capture_or_swallow_stop(self):
        bot = Mock(region=Rect(0, 0, 10, 10), selected_location_name="test")
        capture = Mock()
        with patch("bd2_fishing.app.fishing_task.window.WindowGuard") as guard:
            guard.return_value.side_effect = control.RunStopped("失焦")
            with self.assertRaises(control.RunStopped):
                FishingBot._record_incident(bot, capture, "blocked")
        capture.grab.assert_not_called()

    def test_recovery_evidence_precedes_any_later_action(self):
        bot = Mock(region=Rect(0, 0, 10, 10), selected_location_name="test")
        frame = np.ones((10, 10, 3), np.uint8)
        capture = Mock(grab=Mock(return_value=frame))
        with tempfile.TemporaryDirectory() as directory:
            with (
                incidents.recording_session(directory=directory),
                patch("bd2_fishing.app.fishing_task.window.WindowGuard"),
            ):
                FishingBot._record_incident(bot, capture, "cast_position_blocked")
            capture.grab.assert_called_once_with(bot.region)
            with ZipFile(next(Path(directory).glob("*.zip"))) as archive:
                metadata = json.loads(archive.read("metadata.json"))
            self.assertEqual(metadata["event"], "cast_position_blocked")
            self.assertEqual(metadata["frames"][0]["source"], "incident_game")

    def test_success_cannot_evict_failed_catch(self):
        config = settings.configparser.ConfigParser()
        config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        config.set("diagnostics", "max_events", "1")
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "bd2_fishing.game.fishing.settlement.paths.get_diagnostics_path",
                return_value=directory,
            ),
        ):
            for status in ("unknown", "caught", "caught"):
                observer = CatchObserver(Mock(), config, Rect(0, 0, 875, 492))
                observer.result = CatchResult(status, "test")
                observer.finalize("returned")
                self.assertTrue(observer.save_done.wait(2))
            self.assertEqual(
                len(list((Path(directory) / "catch_result/failures").glob("*.zip"))), 1
            )
            self.assertEqual(len(list((Path(directory) / "catch_result/success").glob("*.zip"))), 1)
