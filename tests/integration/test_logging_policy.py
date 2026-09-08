import configparser
import io
import json
import logging
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

import numpy as np

from bd2_fishing.app import fishing_task as fishing_task
from bd2_fishing.game.fishing.feedback import FeedbackSession
from bd2_fishing.game.fishing.feedback_rules import Outcome
from bd2_fishing.game.fishing.settlement import CatchObserver
from bd2_fishing.infrastructure import paths as paths
from bd2_fishing.infrastructure import settings as settings
from bd2_fishing.infrastructure.diagnostics import logging as logging_setup
from bd2_fishing.infrastructure.diagnostics.qte_evidence import EvidenceWriter
from bd2_fishing.infrastructure.windows import window as window
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime import geometry as geometry
from bd2_fishing.runtime.context import current_round_id, fishing_round, get_logger


@contextmanager
def log_outputs():
    root = logging.getLogger()
    original = root.handlers[:], root.level
    screen, file = io.StringIO(), io.StringIO()
    handlers = [logging.StreamHandler(screen), logging.StreamHandler(file)]
    handlers[0].setLevel(logging.INFO)
    handlers[1].setLevel(logging.DEBUG)
    root.handlers = handlers
    root.setLevel(logging.DEBUG)
    try:
        yield screen, file
    finally:
        root.handlers, root.level = original
        for handler in handlers:
            handler.close()


class LoggingPolicyTests(unittest.TestCase):
    def config(self):
        config = configparser.ConfigParser()
        config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        return config

    def test_round_context_restores_after_nested_stop(self):
        with fishing_round("outer"):
            with self.assertRaises(run_control.RunStopped):
                with fishing_round("inner"):
                    self.assertEqual(current_round_id(), "inner")
                    raise run_control.RunStopped()
            self.assertEqual(current_round_id(), "outer")
        self.assertIsNone(current_round_id())

    def test_main_round_id_matches_cast_bite_and_settlement_and_resets_on_stop(self):
        bot = object.__new__(fishing_task.FishingBot)
        bot.region = geometry.Rect(0, 0, 875, 492)
        bot.config = self.config()
        bot.ocr_context = Mock()
        bot.begin_fish_wait_time = bot.round_end_wait_time = 0
        strategy = Mock(feedback_enabled=True)
        bot.choose_strategy = Mock(return_value=strategy)
        bot.should_change_location = Mock(return_value=False)
        seen = []
        bot.wait_for_bite = Mock(side_effect=lambda _: seen.append(("bite", current_round_id())))

        def play(_):
            seen.append(("qte", strategy.catch_observer.round_id))
            if len([item for item in seen if item[0] == "qte"]) == 2:
                raise run_control.RunStopped("test stop")

        strategy.play_qte.side_effect = play
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "bd2_fishing.game.fishing.settlement.paths.get_base_path", return_value=directory
            ),
            patch("bd2_fishing.app.fishing_task.window.WindowGuard"),
            patch("bd2_fishing.app.fishing_task.DxCameraCapture"),
            patch("bd2_fishing.runtime.control.sleep"),
            patch(
                "bd2_fishing.game.fishing.actions.cast_rod",
                side_effect=lambda: seen.append(("cast", current_round_id())),
            ),
        ):
            with self.assertRaises(run_control.RunStopped):
                bot.run()
            self.assertEqual(len(list(Path(directory).rglob("*.zip"))), 2)
        self.assertEqual([item[0] for item in seen], ["cast", "bite", "qte"] * 2)
        self.assertEqual(len({item[1] for item in seen[:3]}), 1)
        self.assertEqual(len({item[1] for item in seen[3:]}), 1)
        self.assertNotEqual(seen[0][1], seen[3][1])
        self.assertIsNone(current_round_id())

    def test_unknown_attribution_stays_in_file_and_game_hit_stays_on_screen(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            log_outputs() as (screen, file),
            patch(
                "bd2_fishing.game.fishing.settlement.paths.get_base_path", return_value=directory
            ),
        ):
            with fishing_round("round-a"):
                observer = CatchObserver(Mock(), self.config(), geometry.Rect(0, 0, 875, 492))
                session = FeedbackSession(self.config(), observer.window, observer)
            # 后台对象不能误用下一条鱼的上下文。
            with fishing_round("round-b"):
                session.publish(session.tracker.begin(10))
                session.publish(session.tracker.begin(10.2))
                session.publish(session.tracker.observe("hit", 10.3, 0.97))
                session.close()
                observer.finalize("returned")
                self.assertTrue(observer.save_done.wait(2))
            shown, saved = screen.getvalue(), file.getvalue()
            self.assertIn("[轮次=round-a] QTE 反馈 #1：普通命中（HIT）", shown)
            self.assertIn("普通命中=1", shown)
            self.assertIn("按键尝试=2，其中归属未确认=2", shown)
            self.assertNotIn("QTE 按键归属:", shown)
            self.assertNotIn("[轮次=round-b]", saved)
            self.assertEqual(saved.count("QTE 按键归属:"), 2)
            self.assertIn("匹配=0.970", saved)
            with ZipFile(next(Path(directory).rglob("*.zip"))) as z:
                data = json.loads(z.read("metadata.json"))
            self.assertEqual(data["round_id"], "round-a")
            self.assertIn(data["evidence_id"], shown)
            self.assertEqual(len(data["attempt_outcomes"]), 2)

    def test_reused_screenshot_slot_has_distinct_evidence_id_and_bound_round(self):
        with tempfile.TemporaryDirectory() as directory, log_outputs() as (screen, file):
            frame = np.zeros((30, 50, 3), np.uint8)
            ids = []
            for round_id in ("first", "second"):
                with fishing_round(round_id):
                    writer = EvidenceWriter(
                        directory,
                        self.config(),
                        geometry.Rect(0, 0, 50, 30),
                        geometry.Rect(0, 0, 875, 492),
                        max_events=1,
                    )
                writer.submit(Outcome(1, 1, 1.1, "miss", "miss", "test", 0.95), [(1.1, frame)])
                writer.close()
                with ZipFile(next(Path(directory).glob("*.zip"))) as z:
                    data = json.loads(z.read("metadata.json"))
                self.assertEqual(data["round_id"], round_id)
                ids.append(data["evidence_id"])
                self.assertIn(f"[轮次={round_id}] QTE 证据已保存", file.getvalue())
            self.assertNotEqual(*ids)
            self.assertNotIn("QTE 证据已保存", screen.getvalue())

    def test_expected_stop_has_no_traceback_but_capture_error_does(self):
        for error, level, traceback in (
            (run_control.RunStopped("失焦"), logging.DEBUG, False),
            (OSError("capture failed"), logging.ERROR, True),
        ):
            session = FeedbackSession(self.config(), geometry.Rect(0, 0, 875, 492))
            with (
                patch(
                    "bd2_fishing.infrastructure.windows.window.WindowGuard",
                    return_value=Mock(side_effect=error),
                ),
                patch("bd2_fishing.infrastructure.windows.window.enable_dpi_awareness"),
                patch("bd2_fishing.infrastructure.windows.gdi.FeedbackCapture"),
                self.assertLogs("bd2_fishing.game.fishing.feedback", level="DEBUG") as logs,
            ):
                session.run()
            self.assertEqual(logs.records[-1].levelno, level)
            self.assertEqual(logs.records[-1].exc_info is not None, traceback)

    def test_existing_external_handler_cannot_disable_file_logging(self):
        root = logging.getLogger()
        original = root.handlers[:], root.level, logging_setup._fault_file
        external = logging.StreamHandler(io.StringIO())
        root.handlers = [external]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "auto_fishing.fault.log").write_text("previous crash\n", encoding="utf-8")
            try:
                with (
                    patch(
                        "bd2_fishing.infrastructure.diagnostics.logging.get_log_path",
                        return_value=directory,
                    ),
                    patch("faulthandler.enable"),
                ):
                    logging_setup.setup_logging()
                    logging_setup.setup_logging()
                get_logger("test_logging_file").debug("complete debug detail")
                for handler in root.handlers:
                    if getattr(handler, "_bd2_file", False):
                        handler.flush()
                self.assertEqual(sum(getattr(h, "_bd2_file", False) for h in root.handlers), 1)
                self.assertIn(
                    "complete debug detail", (path / "auto_fishing.log").read_text(encoding="utf-8")
                )
                self.assertIn(
                    "previous crash", (path / "auto_fishing.fault.log").read_text(encoding="utf-8")
                )
            finally:
                for handler in root.handlers:
                    if handler is not external:
                        handler.close()
                if logging_setup._fault_file is not original[2]:
                    logging_setup._fault_file.close()
                root.handlers, root.level, logging_setup._fault_file = original
                external.close()
