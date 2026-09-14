"""确认鱼获先保存证据，目标仅按当前任务的确认结果完成。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2

from bd2_fishing.app.fishing_collection import FishingCollection
from bd2_fishing.game.fishing.catalogue import find_fish
from bd2_fishing.game.fishing.recovery import _close_new_panel
from bd2_fishing.game.fishing.settlement_rules import CatchResult
from bd2_fishing.perception.ocr_types import OCRText
from bd2_fishing.runtime.control import RunStopped
from bd2_fishing.runtime.geometry import Rect
from tests.support import ROOT


class FishingCollectionTests(unittest.TestCase):
    def setUp(self):
        self.collection = FishingCollection()
        self.addCleanup(self.collection.journal.close)
        self.fish = find_fish("斗鱼")[0]
        self.collection.save_targets({self.fish.id: "max"})
        self.collection.begin(True)
        frame = cv2.imread(str(ROOT / "tests/fixtures/catch_result/marks_20260914/max_green.png"))
        self.observer = SimpleNamespace(
            result=CatchResult(
                "caught",
                reward="斗鱼×1",
                size_cm=7.5,
                size_kind="max",
                stars=1,
                border_color="green",
            ),
            reward_readings=[OCRText("斗鱼×1", 0.99), OCRText("Maximum Size", 0.99)],
            current_location=self.fish.location,
            round_id="one",
            engine=None,
            evidence_frames={"settlement.png": frame},
            evidence_metadata={},
        )

    def test_confirmation_retains_picture_and_completes_target_once(self):
        self.collection.confirm(self.observer)
        self.collection.confirm(self.observer)
        self.assertTrue(self.collection.completed)
        history = self.collection.journal.history()
        self.assertEqual(len(history), 1)
        self.assertEqual(
            (history[0]["fish_id"], history[0]["stars"], history[0]["size_kind"]),
            (self.fish.id, 1, "max"),
        )
        self.assertIsNotNone(self.collection.picture(history[0]["id"], (80, 60)))

    def test_storage_failure_stops_before_caller_can_close_reward(self):
        with patch.object(self.collection.journal, "record", side_effect=OSError("disk full")):
            with self.assertRaises(RunStopped):
                self.collection.confirm(self.observer)
        self.assertFalse(self.collection.completed)

    def test_name_refinement_failure_keeps_unidentified_catch_and_pending_goal(self):
        self.observer.reward_readings = [OCRText("×1", 0.99), OCRText("Maximum Size", 0.99)]
        self.observer.engine = Mock()
        self.observer.engine.detect_and_recognize.side_effect = RuntimeError("OCR unavailable")
        self.collection.confirm(self.observer)
        self.assertFalse(self.collection.completed)
        self.assertIsNone(self.collection.journal.history()[0]["fish_id"])
        self.assertIn("identity_refinement_error", self.observer.evidence_metadata)

    def test_unconfirmed_result_cannot_create_history_or_complete_target(self):
        self.observer.result.status = "unknown"
        self.collection.confirm(self.observer)
        self.assertFalse(self.collection.completed)
        self.assertEqual(self.collection.journal.history(), [])

    def test_delayed_reward_in_recovery_cannot_close_after_record_failure(self):
        observer = SimpleNamespace(
            evidence_metadata={
                "personal_recording": True,
                "resume_check": {"panel_kind": "result"},
            },
            result=CatchResult(),
            inspect_current_page=Mock(return_value="panel"),
            finish=Mock(side_effect=RunStopped("record failed")),
        )
        with (
            patch("bd2_fishing.game.fishing.recovery.game_input.moveTo"),
            patch("bd2_fishing.game.fishing.recovery.game_input.click") as click,
            patch("bd2_fishing.game.fishing.recovery.control.sleep"),
        ):
            with self.assertRaises(RunStopped):
                _close_new_panel(SimpleNamespace(region=Rect(0, 0, 945, 532)), observer)
        observer.finish.assert_called_once()
        click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
