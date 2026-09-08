"""结算正负实图与证据规则回归，不连接游戏或发送输入。"""

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
from bd2_fishing.game.fishing.settlement import (
    CatchObserver,
    read_settlement_texts,
    run_observed_qte,
)
from bd2_fishing.game.fishing.settlement_rules import classify_settlement
from bd2_fishing.infrastructure import paths as paths
from bd2_fishing.infrastructure import settings as settings
from bd2_fishing.infrastructure.windows import window as window
from bd2_fishing.perception.ocr_types import OCRBox, OCRText
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime import geometry as geometry
from tests.support import ROOT

FIXTURES = ROOT / "tests/fixtures/catch_result"


class CatchResultTests(unittest.TestCase):
    def config(self):
        config = configparser.ConfigParser()
        config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        return config

    def test_reward_requires_panel_quantity_and_size(self):
        reward = [OCRText("鱼×1", 0.86), OCRText("14.7cm", 0.99)]
        result = classify_settlement(True, reward, [], [])
        self.assertEqual((result.status, result.size_cm), ("caught", 14.7))
        self.assertEqual(classify_settlement(False, reward, [], []).status, "unknown")
        self.assertEqual(
            classify_settlement(False, reward, [1, 1], [OCRText("90CM", 0.99)]).status, "unknown"
        )
        self.assertEqual(
            classify_settlement(True, reward[:1], [1, 1], [OCRText("90cm", 0.95)]).status, "unknown"
        )

    def test_empty_scene_and_single_low_timer_do_not_prove_escape(self):
        self.assertEqual(classify_settlement(False, [], [], []).status, "unknown")
        self.assertEqual(
            classify_settlement(False, [], [1], [OCRText("90CM", 0.95)]).status, "unknown"
        )

    def test_timeout_is_explicitly_an_inference(self):
        result = classify_settlement(False, [], [2, 1, 1], [OCRText("9OCM", 0.84)])
        self.assertEqual((result.status, result.remaining_cm), ("suspected_escape", 90))
        self.assertEqual(
            classify_settlement(False, [], [2, 2, 1], [OCRText("90CM", 0.95)]).status,
            "suspected_escape",
        )
        self.assertEqual(
            classify_settlement(False, [], [1, 1], [OCRText("0CM", 0.99)]).status, "unknown"
        )
        self.assertEqual(
            classify_settlement(False, [], [1, 1], [OCRText("90CM", 0.60)]).status, "unknown"
        )

    def test_real_settlement_panel_and_normal_scene_are_distinct(self):
        observer = CatchObserver(Mock(), self.config(), geometry.Rect(0, 0, 875, 492))
        for name, expected in (
            ("caught", True),
            ("caught_unusual_name", True),
            ("normal", False),
            ("escaped_scene", False),
            ("last_qte", False),
        ):
            frame = cv2.imdecode(
                np.frombuffer((FIXTURES / f"{name}.png").read_bytes(), np.uint8), 1
            )
            with self.subTest(name=name):
                self.assertEqual(observer._panel_open(frame), expected)

    def test_timer_ignores_uncertain_text_and_stops_reading_during_settlement(self):
        engine = Mock()
        engine.recognize.side_effect = [OCRText("1", 0.98), OCRText("1", 0.4), OCRText("c", 0.99)]
        observer = CatchObserver(engine, self.config(), geometry.Rect(0, 0, 875, 492))
        frame = np.zeros((143, 350, 3), np.uint8)
        for stamp in (1, 1.5, 2):
            observer.observe_timer(frame, stamp)
        self.assertEqual([r[1] for r in observer.readings], [1])
        observer.settling = True
        observer.observe_timer(frame, 3)
        self.assertEqual(engine.recognize.call_count, 3)

    def test_settlement_uses_existing_wait_budget_and_preserves_click(self):
        strategy = qte_strategy.FrostStraitQTEStrategy(self.config(), geometry.Rect(0, 0, 875, 492))
        strategy.fish_end_wait_time = 4
        strategy.catch_observer = Mock()
        with (
            patch.object(qte_strategy.time, "monotonic", side_effect=[10, 11.5]),
            patch.object(run_control, "sleep") as sleep,
            patch.object(qte_strategy.pydirectinput, "moveTo") as move,
            patch.object(qte_strategy.pydirectinput, "click") as click,
        ):
            strategy._finish_fishing()
        self.assertEqual(sleep.call_args_list[0].args, (2.5,))
        move.assert_called_once_with(437, 246)
        click.assert_called_once_with()

    def test_stop_during_settlement_cannot_reach_click(self):
        strategy = qte_strategy.FrostStraitQTEStrategy(self.config(), geometry.Rect(0, 0, 875, 492))
        strategy.catch_observer = Mock(finish=Mock(side_effect=run_control.RunStopped("stop")))
        with patch.object(qte_strategy.pydirectinput, "click") as click:
            with self.assertRaises(run_control.RunStopped):
                strategy._finish_fishing()
        click.assert_not_called()

    def test_uncertain_fish_name_can_verify_quantity_without_inventing_name(self):
        box = OCRBox(((0, 0), (45, 0), (45, 14), (0, 14)), 0.65)
        engine = Mock()
        engine.detect_and_recognize.return_value = [OCRText("螺x1", 0.65, box)]
        engine.recognize.side_effect = [OCRText("端螺×1", 0.56), OCRText("x1", 0.81)]
        result = read_settlement_texts(engine, np.zeros((30, 70, 3), np.uint8))
        self.assertEqual((result[0].text, result[0].score), ("×1", 0.81))

    def test_refinement_disagreement_does_not_invent_distance(self):
        box = OCRBox(((0, 0), (25, 0), (25, 12), (0, 12)), 0.70)
        engine = Mock()
        engine.detect_and_recognize.return_value = [OCRText("90CM", 0.70, box)]
        engine.recognize.return_value = OCRText("900CM", 0.99)
        result = read_settlement_texts(engine, np.zeros((30, 70, 3), np.uint8))
        self.assertEqual((result[0].text, result[0].score), ("90CM", 0.70))

    def test_interruption_is_not_escape(self):
        observer = CatchObserver(Mock(), self.config(), geometry.Rect(0, 0, 875, 492))
        observer.mark_interrupted()
        self.assertEqual(observer.result.status, "interrupted")

    def test_all_exit_paths_save_final_pending_key_and_cached_frame(self):
        for error, status in (
            (None, "unknown"),
            (run_control.RunStopped("失焦"), "interrupted"),
            (ValueError("test"), "unknown"),
        ):
            with (
                self.subTest(status=status, error=error),
                tempfile.TemporaryDirectory() as directory,
            ):
                observer = CatchObserver(
                    Mock(recognize=Mock(return_value=None)),
                    self.config(),
                    geometry.Rect(0, 0, 875, 492),
                )
                frame = np.full((143, 350, 3), 91, np.uint8)
                observer.observe_timer(frame, 1)
                session = FeedbackSession(self.config(), observer.window, observer)
                session.begin_press()
                strategy = Mock(catch_observer=observer, _stop_feedback=session.close)
                strategy.play_qte.side_effect = error
                with (
                    patch(
                        "bd2_fishing.game.fishing.settlement.paths.get_base_path",
                        return_value=directory,
                    ),
                    patch("bd2_fishing.game.fishing.settlement.FeedbackCapture") as capture,
                ):
                    if error is None:
                        run_observed_qte(strategy, None)
                    else:
                        with self.assertRaises(type(error)):
                            run_observed_qte(strategy, None)
                    observer.finalize("returned")  # 重复收尾不能覆盖原退出状态或重复写入。
                    capture.assert_not_called()
                self.assertTrue(observer.save_done.wait(2))
                archives = list(Path(directory).rglob("*.zip"))
                self.assertEqual(len(archives), 1)
                with ZipFile(archives[0]) as archive:
                    metadata = json.loads(archive.read("metadata.json"))
                    saved = cv2.imdecode(
                        np.frombuffer(archive.read("last_observed_qte.png"), np.uint8), 1
                    )
                self.assertTrue(np.array_equal(saved, frame))
                self.assertEqual(metadata["result"]["status"], status)
                self.assertEqual(
                    [(item["attempt"], item["result"]) for item in metadata["attempt_outcomes"]],
                    [(1, "unknown")],
                )

    def test_ocr_failure_keeps_captured_settlement_and_does_not_block_original_click(self):
        observer = CatchObserver(Mock(), self.config(), geometry.Rect(0, 0, 875, 492))
        strategy = qte_strategy.FrostStraitQTEStrategy(self.config(), observer.window)
        strategy.catch_observer = observer
        frame = np.full((492, 875, 3), 52, np.uint8)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "bd2_fishing.game.fishing.settlement.paths.get_base_path", return_value=directory
            ),
            patch("bd2_fishing.game.fishing.settlement.window.WindowGuard"),
            patch("bd2_fishing.game.fishing.settlement.FeedbackCapture") as capture,
            patch.object(observer, "_panel_open", return_value=True),
            patch(
                "bd2_fishing.game.fishing.settlement.read_settlement_texts",
                side_effect=ValueError("OCR test"),
            ),
            patch.object(run_control, "sleep"),
            patch.object(qte_strategy.pydirectinput, "moveTo"),
            patch.object(qte_strategy.pydirectinput, "click") as click,
        ):
            capture.return_value.__enter__.return_value.grab.return_value = frame
            strategy.play_qte = Mock(side_effect=lambda _: strategy._finish_fishing())
            with self.assertLogs("bd2_fishing.game.fishing.qte", level="ERROR"):
                run_observed_qte(strategy, None)
            click.assert_called_once()
            self.assertTrue(observer.save_done.wait(2))
            with ZipFile(next(Path(directory).rglob("*.zip"))) as archive:
                metadata = json.loads(archive.read("metadata.json"))
                self.assertIn("settlement.png", archive.namelist())
            self.assertEqual(metadata["result"]["status"], "unknown")
            self.assertIn("ValueError", metadata["result"]["reason"])

    def test_no_frames_or_keys_still_leave_an_explicit_unknown_record(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "bd2_fishing.game.fishing.settlement.paths.get_base_path", return_value=directory
            ),
        ):
            observer = CatchObserver(Mock(), self.config(), geometry.Rect(0, 0, 875, 492))
            observer.finalize("returned")
            self.assertTrue(observer.save_done.wait(2))
            with ZipFile(next(Path(directory).rglob("*.zip"))) as archive:
                metadata = json.loads(archive.read("metadata.json"))
            self.assertFalse(metadata["screenshots_available"])
            self.assertEqual(metadata["game_feedback"], [])
            self.assertEqual(metadata["result"]["status"], "unknown")
