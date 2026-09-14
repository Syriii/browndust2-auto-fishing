"""昼夜读数与跨岛目标路由；导航和等待使用替身，不操作游戏。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from bd2_fishing.app.fishing_collection import FishingCollection
from bd2_fishing.app.target_routing import prepare_target_cast
from bd2_fishing.game.fishing.catch_identity import choose_target
from bd2_fishing.game.fishing.daytime import read_daytime
from bd2_fishing.runtime.control import RunStopped
from tests.support import ROOT


class TargetRoutingTests(unittest.TestCase):
    def test_clock_icons_override_sky_background_and_scaling(self):
        # 两张魔鬼鱼 MAX 图的天空都是夜景，实际钟面分别亮月亮、亮太阳。
        for name, expected in (
            ("max_blue", "night"),
            ("max_blue_holdout", "day"),
            ("ordinary_day_green", "day"),
            ("max_green", "night"),
        ):
            frame = cv2.imread(str(ROOT / f"tests/fixtures/catch_result/marks_20260914/{name}.png"))
            for size in ((945, 532), (875, 492), (1152, 648)):
                with self.subTest(name=name, size=size):
                    self.assertEqual(read_daytime(cv2.resize(frame, size)), expected)
        self.assertEqual(read_daytime(np.zeros((532, 945, 3), np.uint8)), "unknown")
        self.assertEqual(read_daytime(None), "unknown")

    def test_choose_current_island_then_other_available_targets(self):
        collection = FishingCollection()
        self.addCleanup(collection.journal.close)
        day = next(f for f in collection.catalogue.values() if f.availability == "day")
        both = next(
            f
            for f in collection.catalogue.values()
            if f.availability == "both" and f.location != day.location
        )
        pending = [(day.id, "max"), (both.id, "min")]
        self.assertEqual(
            choose_target(pending, collection.catalogue, day.location, "day"), day.location
        )
        self.assertEqual(
            choose_target(pending, collection.catalogue, day.location, "night"), both.location
        )
        self.assertIsNone(
            choose_target([(day.id, "max")], collection.catalogue, day.location, "unknown")
        )

    def test_arrival_rechecks_clock_before_cast_and_waits_through_wrong_time(self):
        collection = FishingCollection()
        self.addCleanup(collection.journal.close)
        day = next(f for f in collection.catalogue.values() if f.availability == "day")
        other = next(
            f.location for f in collection.catalogue.values() if f.location != day.location
        )
        collection.save_targets({day.id: "max"})
        collection.begin(True)
        bot = SimpleNamespace(
            collection=collection, region=Mock(), config=Mock(), ocr_context=Mock()
        )
        with (
            patch("bd2_fishing.app.target_routing.window.WindowGuard"),
            patch(
                "bd2_fishing.app.target_routing.detect_location_from_ocr",
                side_effect=[other, day.location, day.location],
            ),
            patch(
                "bd2_fishing.app.target_routing.read_daytime",
                side_effect=["day", "day", "night", "night", "day", "day"],
            ),
            patch(
                "bd2_fishing.app.target_routing.prepare_voyage", return_value=day.location
            ) as navigate,
            patch("bd2_fishing.app.target_routing.confirm_ready_for_next_cast") as ready,
            patch("bd2_fishing.app.target_routing.control.sleep") as sleep,
            patch("bd2_fishing.app.target_routing.control.set_status") as status,
        ):
            prepare_target_cast(bot, Mock())
        navigate.assert_called_once_with(
            bot.config, bot.region, bot.ocr_context.engine, day.location, change_from_island=True
        )
        self.assertEqual(bot.selected_location_name, day.location)
        status.assert_any_call("等待白天")
        sleep.assert_any_call(3)
        self.assertEqual(ready.call_count, 2)

    def test_waiting_remains_cancellable_without_navigation(self):
        collection = FishingCollection()
        self.addCleanup(collection.journal.close)
        day = next(f for f in collection.catalogue.values() if f.availability == "day")
        collection.save_targets({day.id: "min"})
        collection.begin(True)
        bot = SimpleNamespace(
            collection=collection, region=Mock(), config=Mock(), ocr_context=Mock()
        )
        with (
            patch("bd2_fishing.app.target_routing.window.WindowGuard"),
            patch(
                "bd2_fishing.app.target_routing.detect_location_from_ocr", return_value=day.location
            ),
            patch("bd2_fishing.app.target_routing.read_daytime", return_value="unknown"),
            patch("bd2_fishing.app.target_routing.control.sleep", side_effect=RunStopped("stop")),
            patch("bd2_fishing.app.target_routing.prepare_voyage") as navigate,
        ):
            with self.assertRaises(RunStopped):
                prepare_target_cast(bot, Mock())
        navigate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
