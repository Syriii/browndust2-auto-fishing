import ast
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zipfile import ZipFile

import cv2
import numpy as np

from bd2_fishing.game.fishing.hook_diagnostics import HookDiagnostics
from tests.support import ROOT


class HookDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "diagnostics"
        self.recorder = HookDiagnostics(self.output, interval_seconds=0, max_events=2)
        self.region = SimpleNamespace(as_tuple=lambda: (10, 20, 33, 96))
        self.lower = np.array([20, 35, 210])
        self.upper = np.array([30, 120, 255])
        hsv = np.zeros((76, 23, 3), dtype=np.uint8)
        hsv.reshape(-1, 3)[:180] = (25, 80, 240)
        self.peak = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    def save(self, capture=None):
        if capture is None:
            capture = Mock(grab=Mock(return_value=self.peak))
        return self.recorder.save_timeout(
            capture, self.region, self.region, self.lower, self.upper, 212, "深渊巨口"
        )

    def join(self):
        self.recorder._worker.join(timeout=5)
        self.assertFalse(self.recorder._worker.is_alive())

    def latest(self):
        return max(self.output.glob("*.zip"), key=lambda p: p.stat().st_mtime_ns)

    def metadata(self):
        with ZipFile(self.latest()) as archive:
            return json.loads(archive.read("metadata.json"))

    def test_peak_survives_source_mutation_and_reset(self):
        source = self.peak.copy()
        self.recorder.observe(source, 180)
        source[:] = 0
        self.recorder.observe(source, 0)
        self.recorder.observe(None)
        self.assertTrue(self.save())
        self.recorder.reset()
        self.join()
        metadata = self.metadata()
        self.assertEqual(metadata["peak_pixels"], 180)
        self.assertEqual(metadata["valid_frames"], 2)
        self.assertEqual(metadata["none_frames"], 1)
        self.assertEqual(metadata["peak_filter_counts"]["full_hsv"], 180)
        with ZipFile(self.latest()) as archive:
            peak = cv2.imdecode(
                np.frombuffer(archive.read("peak_hook.png"), np.uint8), cv2.IMREAD_COLOR
            )
            last = cv2.imdecode(
                np.frombuffer(archive.read("last_hook.png"), np.uint8), cv2.IMREAD_COLOR
            )
        np.testing.assert_array_equal(peak, self.peak)
        self.assertFalse(last.any())

    def test_zero_pixels_still_preserves_valid_frame(self):
        self.recorder.observe(np.zeros_like(self.peak), 0)
        self.save()
        self.join()
        metadata = self.metadata()
        self.assertEqual(metadata["peak_pixels"], 0)
        self.assertEqual(metadata["valid_frames"], 1)
        self.assertIn("peak_hook.png", metadata["images"])

    def test_existing_incident_frame_is_reused_without_second_capture(self):
        capture = Mock()
        frame = self.peak.copy()
        self.assertTrue(
            self.recorder.save_timeout(
                capture,
                self.region,
                self.region,
                self.lower,
                self.upper,
                212,
                "test",
                context_frame=frame,
            )
        )
        frame[:] = 0
        self.join()
        capture.grab.assert_not_called()
        with ZipFile(self.latest()) as archive:
            saved = cv2.imdecode(np.frombuffer(archive.read("timeout_game.png"), np.uint8), 1)
        np.testing.assert_array_equal(saved, self.peak)
        self.assertEqual(self.metadata()["context_source"], "incident_capture")

    def test_unavailable_incident_frame_does_not_retry_capture(self):
        capture = Mock()
        self.recorder.observe(self.peak, 180)
        self.assertTrue(
            self.recorder.save_timeout(
                capture,
                self.region,
                self.region,
                self.lower,
                self.upper,
                212,
                "test",
                context_frame=None,
            )
        )
        self.join()
        capture.grab.assert_not_called()
        self.assertFalse(self.metadata()["context_available"])
        self.assertIn("peak_hook.png", self.metadata()["images"])

    def test_all_none_is_distinguishable_and_capture_error_is_recorded(self):
        self.recorder.observe(None)
        self.recorder.observe(None)
        self.assertTrue(self.save(Mock(grab=Mock(side_effect=ValueError("Invalid Region")))))
        self.join()
        metadata = self.metadata()
        self.assertEqual(metadata["valid_frames"], 0)
        self.assertEqual(metadata["none_frames"], 2)
        self.assertEqual(metadata["images"], [])
        self.assertEqual(metadata["context_capture_error"], "ValueError: Invalid Region")

    def test_disabled_does_not_capture_or_write(self):
        self.recorder.enabled = False
        capture = Mock()
        self.recorder.observe(self.peak, 180)
        self.assertFalse(self.save(capture))
        capture.grab.assert_not_called()
        self.assertEqual(self.recorder.valid_frames, 0)
        self.assertFalse(self.output.exists())

    def test_interval_skips_extra_capture(self):
        self.recorder.interval_seconds = 60
        self.save()
        self.join()
        capture = Mock()
        self.assertFalse(self.save(capture))
        capture.grab.assert_not_called()

    def test_slow_encoding_is_async_and_busy_writer_drops_new_work(self):
        started = threading.Event()
        release = threading.Event()
        real_encode = cv2.imencode

        def slow_encode(*args):
            started.set()
            if not release.wait(timeout=5):
                raise TimeoutError("Test did not release background writer")
            return real_encode(*args)

        with patch(
            "bd2_fishing.game.fishing.hook_diagnostics.cv2.imencode", side_effect=slow_encode
        ):
            try:
                self.assertTrue(self.save())
                self.assertTrue(started.wait(timeout=5))
                self.assertTrue(self.recorder._worker.is_alive())
                capture = Mock()
                self.assertFalse(self.save(capture))
                capture.grab.assert_not_called()
            finally:
                release.set()
                self.join()

    def test_rotation_replaces_whole_bundle_without_stale_images(self):
        self.recorder.observe(self.peak, 180)
        self.save()
        self.join()
        self.save()
        self.join()
        self.recorder.reset()
        self.recorder.observe(None)
        self.save(Mock(grab=Mock(return_value=None)))
        self.join()
        self.assertEqual(len(list(self.output.glob("*.zip"))), 2)
        with ZipFile(self.latest()) as archive:
            self.assertEqual(archive.namelist(), ["metadata.json"])

    def test_write_failure_releases_writer_and_allows_future_save(self):
        self.recorder.observe(self.peak, 180)
        with patch(
            "bd2_fishing.game.fishing.hook_diagnostics.cv2.imencode",
            side_effect=OSError("disk unavailable"),
        ):
            with self.assertLogs("bd2_fishing.game.fishing.hook_diagnostics", level="WARNING"):
                self.save()
                self.join()
        self.assertTrue(self.save())
        self.join()
        self.assertEqual(len(list(self.output.glob("*.zip"))), 1)


class TimeoutIntegrationTests(unittest.TestCase):
    def test_snapshot_is_submitted_before_recovery_input(self):
        # 只加载真实 wait_for_bite 方法，避免导入原生输入模块或连接游戏。
        source = ROOT / "bd2_fishing" / "app" / "fishing_task.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "wait_for_bite"
        )
        events = []

        class StopTest(Exception):
            pass

        def recover(region):
            events.append("recover")
            raise StopTest()

        namespace = {
            "time": SimpleNamespace(monotonic=Mock(side_effect=[0, 16])),
            "BITE_TIMEOUT_SECONDS": 15,
            "log": Mock(),
            "print": Mock(),
            "run_control": Mock(),
            "fishing_actions": SimpleNamespace(recover_from_timeout=recover),
        }
        module = ast.Module(
            body=[
                ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                method,
            ],
            type_ignores=[],
        )
        exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
        diagnostics = Mock()
        diagnostics.save_timeout.side_effect = lambda *args, **kwargs: events.append("snapshot")
        bot = SimpleNamespace(
            _record_incident=Mock(),
            hook_diagnostics=diagnostics,
            bite_pixel_threshold=212,
            region=None,
            hook_pos=None,
            selected_location_name="深渊巨口",
            hook_yellow_range=SimpleNamespace(lower=None, upper=None),
        )
        with self.assertRaises(StopTest):
            namespace["wait_for_bite"](bot, Mock())
        self.assertEqual(events, ["snapshot", "recover"])


if __name__ == "__main__":
    unittest.main()
