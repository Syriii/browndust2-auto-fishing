"""在真实 MAX 和个人纪录截图上重新执行 OCR，不复用归档识别答案。"""

import unittest
from types import SimpleNamespace

import cv2

from bd2_fishing.app.fishing_collection import FishingCollection
from bd2_fishing.game.fishing.catalogue import find_fish
from bd2_fishing.game.fishing.catch_marks import read_reward_grade
from bd2_fishing.game.fishing.settlement import read_settlement_texts
from bd2_fishing.game.fishing.settlement_rules import classify_settlement
from bd2_fishing.infrastructure.ocr.engine import RapidOCREngine
from tests.support import ROOT


class CatchMarksOCRTests(unittest.TestCase):
    def test_real_low_confidence_name_can_be_refined_before_completing_max(self):
        collection = FishingCollection()
        self.addCleanup(collection.journal.close)
        engine = RapidOCREngine()
        for name, fixture in (
            ("斗鱼", "max_green"),
            ("魔鬼鱼", "max_blue"),
            ("蝴蝶鱼", "max_other_green"),
            ("罗汉鱼", "max_luohan"),
            ("魔鬼鱼", "max_blue_holdout"),
            ("魔鬼鱼", "max_blue_later"),
        ):
            with self.subTest(name=name, fixture=fixture):
                fish = find_fish(name)[0]
                collection.save_targets({fish.id: "max"})
                collection.begin(True)
                frame = cv2.imread(
                    str(ROOT / f"tests/fixtures/catch_result/marks_20260914/{fixture}.png")
                )
                height, width = frame.shape[:2]
                texts = read_settlement_texts(
                    engine,
                    frame[
                        round(height * 0.08) : round(height * 0.21),
                        round(width * 0.36) : round(width * 0.65),
                    ],
                )
                result = classify_settlement(True, texts, [], [])
                result.stars, result.border_color = read_reward_grade(frame, confirmed_catch=True)
                observer = SimpleNamespace(
                    result=result,
                    reward_readings=texts,
                    engine=engine,
                    current_location=fish.location,
                    round_id="real-max",
                    evidence_frames={"settlement.png": frame},
                    evidence_metadata={},
                )
                collection.confirm(observer)
                self.assertTrue(collection.completed)
                self.assertEqual(collection.journal.history()[0]["fish_id"], fish.id)

    def test_live_ocr_on_independent_reward_frames(self):
        engine = RapidOCREngine()
        for name, kind, new_record in (
            ("max_green", "max", False),
            ("max_blue_holdout", "max", False),
            ("new_record_blue", "unknown", True),
        ):
            with self.subTest(name=name):
                frame = cv2.imread(
                    str(ROOT / f"tests/fixtures/catch_result/marks_20260914/{name}.png")
                )
                height, width = frame.shape[:2]
                reward = frame[
                    round(height * 0.08) : round(height * 0.21),
                    round(width * 0.36) : round(width * 0.65),
                ]
                texts = read_settlement_texts(engine, reward)
                result = classify_settlement(True, texts, [], [])
                self.assertEqual(
                    (result.status, result.size_kind, result.new_record),
                    ("caught", kind, new_record),
                )
