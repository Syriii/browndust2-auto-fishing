"""可重复的校准时钟、取消和配置隔离测试，不控制游戏。"""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bd2_fishing.app.calibration import measure_waits
from bd2_fishing.app.desktop import DesktopServices


class CalibrationTests(unittest.TestCase):
    def measure(self, overhead):
        clock = [0.0]

        def wait(seconds):
            clock[0] += seconds + overhead
            return False

        return measure_waits(Mock(wait=Mock(side_effect=wait)), clock=lambda: clock[0])

    def test_small_stable_wait_selects_only_poll_intervals(self):
        report = self.measure(0.001)
        self.assertEqual(
            report["recommendation"], {"loop_sleep_seconds": "5", "feedback_poll_seconds": "10"}
        )
        self.assertEqual(report["waits"][0]["p95_ms"], 6)
        self.assertTrue(all(len(row["samples_ms"]) == 32 for row in report["waits"]))

    def test_large_jitter_refuses_automatic_values(self):
        self.assertEqual(self.measure(0.05)["recommendation"], {})

    def test_rare_large_spike_cannot_hide_below_p95(self):
        clock = [0.0]
        counts = {}

        def wait(seconds):
            counts[seconds] = counts.get(seconds, 0) + 1
            clock[0] += seconds + (0.08 if counts[seconds] == 12 else 0.001)
            return False

        report = measure_waits(Mock(wait=Mock(side_effect=wait)), clock=lambda: clock[0])
        self.assertEqual(report["recommendation"], {})
        self.assertTrue(all(row["outlier_count"] == 1 for row in report["waits"]))
        self.assertEqual(report["waits"][0]["p95_ms"], 6)

    def test_invalid_clock_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "计时无效"):
            measure_waits(Mock(wait=Mock(return_value=False)), clock=lambda: float("nan"))

    def test_feedback_recommendation_must_itself_pass_stability_check(self):
        clock = [0.0]

        def wait(seconds):
            clock[0] += seconds + (0.05 if seconds == 0.01 else 0.001)
            return False

        report = measure_waits(Mock(wait=Mock(side_effect=wait)), clock=lambda: clock[0])
        self.assertEqual(
            report["recommendation"], {"loop_sleep_seconds": "5", "feedback_poll_seconds": "20"}
        )

    def test_no_game_still_saves_calibration_without_creating_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            service = DesktopServices(config_path=path)
            with (
                patch.object(service, "inspect_device", side_effect=RuntimeError("未找到游戏")),
                patch(
                    "bd2_fishing.app.calibration.measure_waits", return_value=self.measure(0.001)
                ),
            ):
                report = service.calibrate_timing(threading.Event())
            self.assertIsNone(report["device"])
            self.assertIn("未找到游戏", report["device_error"])
            self.assertTrue(report["recommendation"])
            self.assertFalse(path.exists())
            self.assertTrue(Path(report["report_path"]).exists())

    def test_cancelled_before_start_never_inspects_device(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(DesktopServices, "inspect_device") as inspect:
            with self.assertRaisesRegex(RuntimeError, "取消"):
                DesktopServices().calibrate_timing(cancel)
            inspect.assert_not_called()

    def test_cancellation_interrupts_measurement(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(RuntimeError, "取消"):
            measure_waits(cancel)

    def test_report_saved_separately_without_changing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text("[time]\nqte_hold_seconds = 0.08\n", encoding="utf8")
            before = path.read_bytes()
            service = DesktopServices(config_path=path)
            with (
                patch.object(service, "inspect_device", return_value={"width": 945, "height": 532}),
                patch(
                    "bd2_fishing.app.calibration.measure_waits", return_value=self.measure(0.001)
                ),
            ):
                result = service.calibrate_timing(threading.Event())
            self.assertEqual(path.read_bytes(), before)
            saved = json.loads(Path(result["report_path"]).read_text(encoding="utf8"))
            self.assertEqual(saved["device"]["width"], 945)
            self.assertEqual(list(Path(directory).rglob("*.tmp")), [])

    def test_cancelled_report_does_not_replace_previous_report(self):
        with tempfile.TemporaryDirectory() as directory:
            service = DesktopServices(config_path=Path(directory) / "config.ini")
            target = Path(directory) / "calibration" / "latest.json"
            target.parent.mkdir()
            target.write_text("previous", encoding="utf8")
            cancel = threading.Event()
            cancel.set()
            with patch.object(service, "inspect_device", return_value={}):
                with self.assertRaisesRegex(RuntimeError, "取消"):
                    service.calibrate_timing(cancel)
            self.assertEqual(target.read_text(), "previous")
