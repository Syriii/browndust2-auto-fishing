import hashlib
import json
from importlib.resources import files
from unittest import TestCase

from bd2_fishing.app.fish_catalogue import GUIDE_TEXT, FishCatalogueService
from bd2_fishing.game.fishing.mechanics.catalogue import MECHANISM_IDS


class FishCatalogueBrowserTests(TestCase):
    def setUp(self):
        self.service = FishCatalogueService()

    def test_all_images_are_offline_originals_and_only_fish_region_is_rendered(self):
        resources = files("bd2_fishing.game.fishing")
        data = json.loads(resources.joinpath("assets/fish_catalogue.json").read_text("utf8"))
        for row in data["fish"]:
            with self.subTest(fish=row["id"]):
                raw = resources.joinpath(row["image"]["runtime_asset"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), row["image"]["sha256"])
                image = self.service.picture(row["id"], (150, 104))
                self.assertLessEqual(image.width, 150)
                self.assertLessEqual(image.height, 104)
                self.assertGreater(image.width / image.height, 1.4)

    def test_partial_search_accepts_traditional_and_registered_regional_aliases(self):
        a = self.service.search(" 布 蘭 ")
        b = self.service.search("布兰什")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 1)
        self.assertEqual(self.service.search("拿破崙"), self.service.search("波纹唇"))
        self.assertEqual(self.service.search("不存在的鱼"), ())

    def test_time_filters_include_all_day_fish_and_combine_with_island_rarity(self):
        day = self.service.search(time="白天")
        night = self.service.search(time="夜晚")
        self.assertTrue(all(f.availability in {"day", "both"} for f in day))
        self.assertTrue(all(f.availability in {"night", "both"} for f in night))
        self.assertEqual(
            {f.id for f in day} & {f.id for f in night},
            {f.id for f in self.service.fish if f.availability == "both"},
        )
        sky = self.service.search("布蘭", island="天空岛", time="白天", rarity="传说")
        expected = tuple(
            f
            for f in self.service.search("布蘭")
            if f.location.value == "天空岛"
            and f.availability in {"day", "both"}
            and f.rarity == "legendary"
        )
        self.assertEqual(sky, expected)

    def test_details_preserve_disputed_bubble_and_do_not_claim_catch_progress(self):
        fish = self.service.search("布拉德")[0]
        detail = self.service.details(fish.id)
        names = {name for name, _ in detail["mechanisms"]}
        self.assertIn("海草泡泡球", names)
        self.assertIn("反弹壁", names)
        self.assertEqual([name for name, _ in detail["facts"]], ["稀有度", "钓场", "时段"])
        self.assertEqual(set(GUIDE_TEXT), MECHANISM_IDS)
        with self.assertRaises(KeyError):
            self.service.picture("../missing", (150, 104))

    def test_catalogue_preview_flag_cannot_start_normal_game_or_update_recovery(self):
        from contextlib import nullcontext
        from unittest.mock import patch

        from bd2_fishing import bootstrap

        with (
            patch("sys.argv", ["BD2_AutoFishing.exe", "--preview-catalogue"]),
            patch("sys.frozen", True, create=True),
            patch(
                "bd2_fishing.infrastructure.updates.transaction.installation_lock",
                return_value=nullcontext(),
            ),
            patch.object(bootstrap, "_desktop") as desktop,
            patch.object(bootstrap, "_recover_pending") as recover,
        ):
            bootstrap.main()
            desktop.assert_called_once_with(True, catalogue=True)
            recover.assert_not_called()
