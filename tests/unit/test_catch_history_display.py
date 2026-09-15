"""历史名称关联只用于展示；不放宽新捕获确认或改写旧目标。"""

from datetime import datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from bd2_fishing.app.fish_catalogue import FishCatalogueService
from bd2_fishing.game.fishing.catch_identity import identify_catch
from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.infrastructure.fishing_journal import FishingJournal
from bd2_fishing.perception.ocr_types import OCRText


class CatchHistoryDisplayTests(TestCase):
    def setUp(self):
        self.service = FishCatalogueService()

    def test_old_quantity_names_resolve_to_unique_reference_without_mutating_record(self):
        for name, identity in (
            ("蓝龙海神x1", "fish_05_03"),
            ("蓝龙海神鳃 × 1", "fish_05_03"),
            ("鸳鸯鱼×1", "fish_05_08"),
            ("蝴蝶鱼×1", "fish_05_07"),
            ("丝带鳗ｘ１", "fish_05_12"),
        ):
            item = dict(fish_id=None, name=name, location="亚特兰蒂斯")
            before = dict(item)
            self.assertEqual(self.service.catch_reference(item).id, identity)
            self.assertEqual(item, before)

    def test_partial_names_wrong_island_and_ambiguous_matches_stay_unconfirmed(self):
        for name, location in (("鱼×1", "亚特兰蒂斯"), ("蓝龙海神x1", "烟波湖")):
            self.assertIsNone(
                self.service.catch_reference(dict(fish_id=None, name=name, location=location))
            )
        with patch("bd2_fishing.app.fish_catalogue.find_fish", return_value=self.service.fish[:2]):
            self.assertIsNone(
                self.service.catch_reference(dict(fish_id=None, name="鱼", location="未确认"))
            )

    def test_verified_client_names_still_require_confident_catch_ocr(self):
        for name, identity in (
            ("蓝龙海神鳃×1", "fish_05_03"),
            ("鸳鸯鱼x1", "fish_05_08"),
            ("神仙鱼x1", "fish_05_04"),
        ):
            fish, _ = identify_catch([OCRText(name, 0.99)], FishingLocation.ATLANTIS)
            self.assertEqual(fish.id, identity)
            fish, _ = identify_catch([OCRText(name, 0.85)], FishingLocation.ATLANTIS)
            self.assertIsNone(fish)

    def test_unknown_display_name_does_not_invent_missing_ocr_text(self):
        self.assertEqual(self.service.catch_name("鱼×1"), "鱼种未确认")
        self.assertEqual(self.service.catch_name("未登记鱼×2"), "未登记鱼")

    def test_icon_reference_recognizes_two_independent_catches_with_missing_name(self):
        folder = Path("tests/fixtures/catch_result/names_20260915")
        for suffix in ("holdout-1", "holdout-2"):
            raw = (folder / f"silver-pomfret-{suffix}.jpg").read_bytes()
            fish = self.service.catch_image_reference(raw, "亚特兰蒂斯")
            self.assertEqual(fish.id, "fish_05_06")
            self.assertIsNone(self.service.catch_image_reference(raw, "烟波湖"))

    def test_icon_reference_rejects_other_fish_corrupt_images_and_unknown_location(self):
        folder = Path("tests/fixtures/catch_result/names_20260915")
        for name in ("blue-dragon", "mandarinfish"):
            self.assertIsNone(
                self.service.catch_image_reference(
                    (folder / f"{name}.jpg").read_bytes(), "亚特兰蒂斯"
                )
            )
        for raw in (None, b"broken jpeg"):
            self.assertIsNone(self.service.catch_image_reference(raw, "亚特兰蒂斯"))
        raw = (folder / "silver-pomfret.jpg").read_bytes()
        self.assertIsNone(self.service.catch_image_reference(raw, "未确认"))


class CatchDatesTests(TestCase):
    def setUp(self):
        self.journal = FishingJournal()
        self.addCleanup(self.journal.close)
        for index, caught_at in enumerate(
            (
                "2026-09-15T00:30:00+00:00",
                "2026-09-15T07:00:00+08:00",
                "2026-09-13T12:00:00+00:00",
                "invalid timestamp",
            )
        ):
            self.journal.record(
                dict(
                    run_id="dates",
                    round_id=str(index),
                    caught_at=caught_at,
                    fish_id="fish_05_03",
                    name="蓝龙海神鳃",
                    location="亚特兰蒂斯",
                    size_cm=4,
                    size_kind="max" if index == 0 else "unknown",
                    rarity="common",
                ),
                None,
            )

    def test_history_sorts_by_actual_time_not_insertion_or_timezone_text(self):
        self.assertEqual([row["id"] for row in self.journal.history()], [1, 2, 3, 4])

    def test_local_date_filter_combines_with_achievement_filter(self):
        day = datetime.fromisoformat("2026-09-15T00:30:00+00:00").astimezone().date().isoformat()
        self.assertEqual([row["id"] for row in self.journal.history("max", day=day)], [1])
        self.assertIn(day, self.journal.history_dates())
        for row in self.journal.history(day=day):
            self.assertEqual(
                datetime.fromisoformat(row["caught_at"]).astimezone().date().isoformat(), day
            )
        self.assertEqual(self.journal.history(day="2099-01-01"), [])

    def test_invalid_dates_remain_accessible_without_being_assigned_to_today(self):
        self.assertEqual([row["id"] for row in self.journal.history(day="unknown")], [4])
        self.assertIn(None, self.journal.history_dates())
