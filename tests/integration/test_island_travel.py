"""换岛结果确认失败不能继续抛竿；所有设备与游戏动作均为替身。"""

import configparser
import unittest
from unittest.mock import Mock, patch

from bd2_fishing.app.fishing_task import FishingBot
from bd2_fishing.game.fishing import actions
from bd2_fishing.game.islands import reading, travel
from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.infrastructure import settings
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class IslandTravelTests(unittest.TestCase):
    def setUp(self):
        self.config = configparser.ConfigParser()
        self.config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        self.region = Rect(0, 0, 945, 532)
        self.context = Mock(enabled=True, engine=Mock())

    def test_every_supported_origin_returns_via_expected_transit(self):
        for origin in FishingLocation:
            transit = (
                FishingLocation.SHALLOW_SHORE
                if origin == FishingLocation.YANBO_LAKE
                else FishingLocation.YANBO_LAKE
            )
            with (
                self.subTest(origin=origin),
                patch.object(travel, "prepare_voyage", side_effect=[transit, origin]) as navigate,
            ):
                travel.change_location(self.config, self.region, self.context, origin)
                self.assertEqual([c.args[3] for c in navigate.call_args_list], [transit, origin])
                self.assertTrue(
                    all(c.kwargs["change_from_island"] for c in navigate.call_args_list)
                )

    def test_first_leg_failure_never_starts_second_leg(self):
        for outcome in (None, FishingLocation.ATLANTIS, travel.NavigationFailed("timeout")):
            with (
                self.subTest(outcome=outcome),
                patch.object(travel, "prepare_voyage", side_effect=[outcome]) as navigate,
            ):
                with self.assertRaises(travel.LocationChangeFailed):
                    travel.change_location(
                        self.config, self.region, self.context, FishingLocation.ATLANTIS
                    )
                self.assertEqual(navigate.call_count, 1)

    def test_failed_return_does_not_report_success(self):
        with patch.object(
            travel,
            "prepare_voyage",
            side_effect=[FishingLocation.YANBO_LAKE, travel.NavigationFailed("return timeout")],
        ) as navigate:
            with self.assertRaisesRegex(travel.LocationChangeFailed, "亚特兰蒂斯"):
                travel.change_location(
                    self.config, self.region, self.context, FishingLocation.ATLANTIS
                )
            self.assertEqual(navigate.call_count, 2)

    def test_missing_ocr_or_disabled_confirmation_never_leaves(self):
        contexts = (Mock(enabled=False, engine=Mock()), Mock(enabled=True, engine=None))
        with patch.object(travel, "prepare_voyage") as navigate:
            for context in contexts:
                with self.assertRaises(travel.LocationChangeFailed):
                    travel.change_location(
                        self.config, self.region, context, FishingLocation.ATLANTIS
                    )
            self.config.set("navigation", "confirm_island_change", "false")
            with self.assertRaises(travel.LocationChangeFailed):
                travel.change_location(
                    self.config, self.region, self.context, FishingLocation.ATLANTIS
                )
            navigate.assert_not_called()

    def test_unsupported_origin_never_leaves(self):
        with patch.object(travel, "prepare_voyage") as navigate:
            for origin in (None, "天空岛"):
                with self.assertRaises(travel.LocationChangeFailed):
                    travel.change_location(self.config, self.region, self.context, origin)
            navigate.assert_not_called()

    def test_missing_ocr_or_empty_text_does_not_trigger_refresh(self):
        with patch.object(reading, "get_texts_from_ocr") as recognize:
            self.assertFalse(reading.check_if_time_to_change_location(Mock(), Mock(enabled=False)))
            self.assertFalse(
                reading.check_if_time_to_change_location(Mock(), Mock(enabled=True, engine=None))
            )
            recognize.assert_not_called()
            for texts, expected in (
                (None, False),
                ([], False),
                ([" "], False),
                (["还剩5小时"], False),
                (["还剩23分钟"], True),
            ):
                recognize.return_value = texts
                self.assertEqual(
                    reading.check_if_time_to_change_location(Mock(), self.context), expected
                )

    def test_failed_change_records_incident_and_cannot_cast(self):
        config = configparser.ConfigParser()
        config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        capture = Mock()
        capture.__enter__ = Mock(return_value=capture)
        capture.__exit__ = Mock(return_value=False)
        bot = FishingBot(
            config, Rect(0, 0, 875, 492), Mock(), capture_factory=Mock(return_value=capture)
        )
        bot.choose_strategy = Mock()
        bot.should_change_location = Mock(return_value=True)
        bot._record_incident = Mock()
        with (
            patch("bd2_fishing.app.fishing_task.window.WindowGuard"),
            patch("bd2_fishing.game.fishing.startup.prepare_start", return_value="idle"),
            patch("bd2_fishing.game.fishing.settlement.confirm_ready_for_next_cast"),
            patch.object(control, "sleep"),
            patch.object(
                travel, "change_location", side_effect=travel.LocationChangeFailed("timeout")
            ),
            patch.object(actions, "cast_rod") as cast,
        ):
            with self.assertRaises(travel.LocationChangeFailed):
                bot.run()
        bot._record_incident.assert_called_once_with(capture, "location_change_failed")
        cast.assert_not_called()
        capture.__exit__.assert_called_once()

    def test_bot_refreshes_and_rechecks_idle_after_both_legs(self):
        bot = FishingBot(self.config, self.region, self.context)
        bot.selected_location_name = FishingLocation.ATLANTIS
        bot.should_change_location = Mock(return_value=True)
        stages = []

        def navigate(*args, **kwargs):
            stages.append(args[3])
            self.assertIs(args[0], self.config)
            self.assertEqual(args[1], self.region)
            self.assertIs(args[2], self.context.engine)
            return args[3]

        with (
            patch.object(travel, "prepare_voyage", side_effect=navigate),
            patch(
                "bd2_fishing.game.fishing.settlement.confirm_ready_for_next_cast",
                side_effect=lambda *args: stages.append("idle_check"),
            ),
        ):
            bot._prepare_cast(Mock())
        self.assertEqual(
            stages,
            ["idle_check", FishingLocation.YANBO_LAKE, FishingLocation.ATLANTIS, "idle_check"],
        )

    def test_stop_between_legs_does_not_start_return(self):
        task_control = control.RunControl()

        def stop_on_arrival(*args, **kwargs):
            task_control.stopped.set()
            return FishingLocation.YANBO_LAKE

        with (
            control.use_control(task_control),
            patch.object(travel, "prepare_voyage", side_effect=stop_on_arrival) as navigate,
        ):
            with self.assertRaises(control.RunStopped):
                travel.change_location(
                    self.config, self.region, self.context, FishingLocation.ATLANTIS
                )
            self.assertEqual(navigate.call_count, 1)

    def test_stop_during_navigation_is_not_wrapped(self):
        with patch.object(travel, "prepare_voyage", side_effect=control.RunStopped("focus")):
            with self.assertRaises(control.RunStopped):
                travel.change_location(
                    self.config, self.region, self.context, FishingLocation.ATLANTIS
                )
