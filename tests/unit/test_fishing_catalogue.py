import copy
import json
from collections import Counter
from importlib.resources import files
from unittest import TestCase

from bd2_fishing.game.fishing.catalogue import find_fish, load_catalogue, parse_catalogue
from bd2_fishing.game.fishing.mechanics.catalogue import MECHANISM_IDS, review_cues
from bd2_fishing.game.islands.catalog import FishingLocation


class FishingCatalogueTests(TestCase):
    def test_six_islands_and_all_reference_mechanisms_are_represented(self):
        fish = load_catalogue()
        counts = Counter(item.location for item in fish)
        self.assertEqual(list(counts.values()), [14, 14, 14, 14, 15, 13])
        self.assertEqual(len({item.id for item in fish}), 84)
        self.assertEqual(set().union(*(f.possible_mechanisms for f in fish)), MECHANISM_IDS)
        self.assertEqual(
            {f.id for f in fish if f.client_name_verified},
            {
                "fish_05_01",
                "fish_05_03",
                "fish_05_04",
                "fish_05_05",
                "fish_05_06",
                "fish_05_07",
                "fish_05_08",
                "fish_05_11",
            },
        )

    def test_regional_translations_and_table_typo_resolve_to_same_species(self):
        for aliases in (
            ("波纹唇鱼", "拿破崙魚", "拿破仑鱼"),
            ("罗汉鱼", "花羅漢", "花罗汉"),
            ("蝴蝶鱼", "蝶魚", "蝶鱼"),
            ("蓝龙海神鳃", "蓝龙海神", "海蛞蝓"),
            ("鸳鸯鱼", "七彩麒麟鱼", "七彩麒麟魚"),
            ("布兰什", "布蘭琪", "布兰琪"),
            ("巨骨舌鱼", "巨骨蛇魚"),
            ("龙睛金鱼", "龍晴金魚", "龍睛金魚"),
            ("条石鲷", "條石雕", "條石鯛"),
        ):
            results = [find_fish(alias) for alias in aliases]
            self.assertTrue(all(len(result) == 1 for result in results))
            self.assertEqual(len({result[0].id for result in results}), 1)
        self.assertEqual(find_fish("布兰"), ())
        self.assertEqual(find_fish(" "), ())
        self.assertEqual(find_fish(" 布 兰 琪 "), find_fish("布兰什"))
        self.assertEqual(find_fish("布兰什", location=FishingLocation.YANBO_LAKE), ())

    def test_brad_uses_union_and_does_not_need_source_agreement(self):
        self.assertEqual(
            find_fish("布拉德")[0].possible_mechanisms,
            {"wall", "clones", "bubble", "yellow_hide"},
        )
        self.assertEqual(find_fish("布兰什")[0].location, FishingLocation.SKY_ISLAND)

    def test_corrupt_or_incomplete_mechanism_union_is_rejected(self):
        data = json.loads(
            files("bd2_fishing.game.fishing")
            .joinpath("assets/fish_catalogue.json")
            .read_text("utf8")
        )
        for key, value in (("possible_mechanisms", ["new_skill"]), ("availability", "morning")):
            changed = copy.deepcopy(data)
            changed["fish"][0][key] = value
            with self.assertRaises(ValueError):
                parse_catalogue(changed)
        data["fish"].append(data["fish"][0])
        with self.assertRaises(ValueError):
            parse_catalogue(data)

    def test_unknown_and_ambiguous_cues_are_not_relabelled_as_confirmed(self):
        result = review_cues(("green_content", "future_skill", "green_content"))
        self.assertEqual(result["possible_mechanisms"], ["bubble", "green_hold"])
        self.assertEqual(result["unmapped_cues"], ["future_skill"])
        self.assertEqual(result["identity"], "unconfirmed")
        empty = review_cues(())
        self.assertTrue(empty["no_signature"])
        self.assertEqual(empty["identity"], "unconfirmed")
