"""尺寸标记、奖励等级及目标完成条件互不混用。"""

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import cv2
import numpy as np

from bd2_fishing.game.fishing.catch_marks import parse_size_marks, read_reward_grade
from bd2_fishing.game.fishing.settlement_rules import classify_settlement
from bd2_fishing.infrastructure.fishing_journal import FishingJournal
from bd2_fishing.perception.ocr_types import OCRText
from tests.support import ROOT

FIXTURES = ROOT / "tests/fixtures/catch_result/marks_20260914"


class CatchMarkTests(unittest.TestCase):
    def test_real_archived_ocr_labels(self):
        for row in json.loads((FIXTURES / "provenance.json").read_text(encoding="utf-8")):
            with self.subTest(file=row["file"]):
                texts = [OCRText(t["text"], t["score"]) for t in row["reward_texts"]]
                result = classify_settlement(True, texts, [], [])
                self.assertEqual(result.status, "caught")
                expected = "max" if row["file"].startswith("max_") else "unknown"
                self.assertEqual(result.size_kind, expected)
                self.assertEqual(result.new_record, row["file"].startswith("new_record_"))
                self.assertEqual(classify_settlement(False, texts, [], []).size_kind, "unknown")

    def test_min_text_contract_is_not_a_real_screenshot_claim(self):
        for token in ("MIN", "Minimum Size", "4.2 cm Minimum Size"):
            self.assertEqual(parse_size_marks([OCRText(token, 0.99)]).kind, "min")

    def test_ambiguous_or_untrusted_labels_cannot_complete_size_goal(self):
        for texts in (
            [OCRText("Maximum Size", 0.70)],
            [OCRText("Maximum Size", 0.99), OCRText("Minimum Size", 0.99)],
            [OCRText("New Record", 0.99)],
            [OCRText("600cm", 0.99)],
            [OCRText("最大纪录", 0.99)],
            [OCRText("说明 Maximum Size", 0.99)],
        ):
            self.assertEqual(parse_size_marks(texts).kind, "unknown")

    def test_real_grade_colors_and_scaled_replays(self):
        for row in json.loads((FIXTURES / "provenance.json").read_text(encoding="utf-8")):
            frame = cv2.imread(str(FIXTURES / row["file"]))
            for width, height in ((945, 532), (875, 492), (1152, 648)):
                with self.subTest(file=row["file"], width=width):
                    resized = cv2.resize(frame, (width, height))
                    self.assertEqual(
                        read_reward_grade(resized, confirmed_catch=True),
                        (row["stars"], row["border"]),
                    )
            self.assertEqual(read_reward_grade(frame), (None, "unknown"))

    def test_background_or_border_alone_cannot_supply_grade(self):
        frame = cv2.imread(str(FIXTURES / "max_blue.png"))
        frame[54:68, 408:431] = 0  # 合成遮挡角标，不是另一个真实样本。
        self.assertEqual(read_reward_grade(frame, confirmed_catch=True), (None, "unknown"))
        for frame in (None, np.zeros((532, 945, 3), np.uint8)):
            self.assertEqual(read_reward_grade(frame, confirmed_catch=True), (None, "unknown"))

    def test_journal_keeps_grade_and_new_record_separate_from_max_min(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            closing(FishingJournal(Path(folder) / "catches.sqlite3")) as journal,
        ):
            path = Path(folder) / "catches.sqlite3"
            journal.replace_targets([("fish", "max"), ("fish", "min")])
            journal.begin_run("active", True)
            event = dict(
                run_id="active",
                round_id="1",
                caught_at="2026-09-14",
                fish_id="fish",
                name="鱼",
                location="湖",
                size_cm=7.5,
                size_kind="unknown",
                rarity="common",
                stars=2,
                border_color="blue",
                new_record=True,
            )
            journal.record(event, b"evidence")
            self.assertEqual(len(journal.targets()), 2)
            row = journal.history()[0]
            self.assertEqual((row["stars"], row["border_color"], row["new_record"]), (2, "blue", 1))
            journal.record(dict(event, round_id="2", size_kind="max", new_record=False), b"max")
            self.assertEqual(journal.targets(), [("fish", "min")])
            self.assertFalse(
                journal.record(dict(event, round_id="2", size_kind="min"), b"duplicate")
            )
            self.assertEqual(journal.targets(), [("fish", "min")])
            journal.record(dict(event, run_id="old", round_id="3", size_kind="min"), b"old")
            self.assertEqual(journal.targets(), [("fish", "min")])
            journal.record(dict(event, round_id="3", size_kind="min"), b"min")
            self.assertEqual(journal.targets(), [])
            with closing(FishingJournal(path)) as reopened:
                self.assertEqual(len(reopened.history()), 4)
                self.assertEqual(len(reopened.history("max")), 1)
                self.assertEqual(len(reopened.history("first")), 1)


if __name__ == "__main__":
    unittest.main()
