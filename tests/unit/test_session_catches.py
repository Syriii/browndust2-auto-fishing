"""本轮筛选和漏字鱼图的真实样本，不操作游戏。"""

import unittest

from bd2_fishing.app.fish_catalogue import FishCatalogueService
from bd2_fishing.infrastructure.fishing_journal import FishingJournal
from tests.support import ROOT


class SessionCatchTests(unittest.TestCase):
    def test_client_angelfish_name_resolves_without_changing_saved_record(self):
        service = FishCatalogueService()
        record = {"fish_id": None, "name": "神仙鱼x1", "location": "亚特兰蒂斯"}
        before = dict(record)
        fish = service.catch_reference(record)
        self.assertEqual(fish.id, "fish_05_04")
        self.assertEqual(fish.name, "神仙鱼")
        self.assertEqual(service.search("天使鱼")[0].id, fish.id)
        self.assertEqual(service.search("天使魚")[0].id, fish.id)
        self.assertEqual(record, before)
        self.assertIsNone(service.catch_reference({**record, "location": "烟波湖"}))

    def test_ribbon_eel_holdout_and_other_fish_are_distinct(self):
        service = FishCatalogueService()
        for identity in (233, 246):
            raw = (
                ROOT / f"tests/fixtures/catch_result/ribbon_eel_20260915/catch-{identity}.jpg"
            ).read_bytes()
            fish = service.catch_image_reference(raw, "亚特兰蒂斯")
            self.assertIsNotNone(fish)
            self.assertEqual(fish.id, "fish_05_12")
            self.assertIsNone(service.catch_image_reference(raw, "烟波湖"))
        for path in (ROOT / "tests/fixtures/catch_result/marks_20260914").glob("*.png"):
            fish = service.catch_image_reference(path.read_bytes(), "亚特兰蒂斯")
            self.assertNotEqual(fish.id if fish else None, "fish_05_12", path.name)

    def test_run_filter_precedes_limit_and_does_not_change_targets(self):
        journal = FishingJournal()
        self.addCleanup(journal.close)
        journal.replace_targets([("fish_05_12", "max")])
        for index in range(35):
            event = dict(
                run_id="current" if index % 2 else "previous",
                round_id=str(index),
                caught_at=f"2026-09-15T01:00:{index:02d}+00:00",
                fish_id=None,
                name="丝带x1",
                location="亚特兰蒂斯",
                size_cm=94,
                size_kind="unknown",
                rarity="unknown",
            )
            journal.record(event, None)
        before = journal.history(limit=100)
        rows = journal.history(run_id="current", limit=3)
        self.assertEqual([row["id"] for row in rows], [34, 32, 30])
        self.assertEqual(journal.run_count("current"), 17)
        self.assertEqual(journal.history(run_id="absent"), [])
        self.assertEqual(journal.targets(), [("fish_05_12", "max")])
        self.assertEqual(journal.history(limit=100), before)
