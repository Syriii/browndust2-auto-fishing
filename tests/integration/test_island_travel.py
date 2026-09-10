"""换岛结果确认失败不能继续抛竿；所有设备与游戏动作均为替身。"""

import configparser
import unittest
from unittest.mock import Mock, patch

from bd2_fishing.app.fishing_task import FishingBot
from bd2_fishing.game.fishing import actions
from bd2_fishing.game.islands import travel
from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.infrastructure import settings
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect


class IslandTravelTests(unittest.TestCase):
    def test_confirmation_timeout_raises_and_polls_with_wait(self):
        with (
            patch.object(travel, "click_change_btn"),
            patch.object(travel, "click_button"),
            patch.object(travel.run_control, "sleep") as sleep,
            patch.object(travel, "check_if_have_keyword", return_value=False),
            patch.object(travel.time, "monotonic", side_effect=[0, 0, 11]),
        ):
            with self.assertRaises(travel.LocationChangeFailed):
                travel.change_location(Mock(), Mock(), FishingLocation.YANBO_LAKE)
            self.assertIn(((0.2,), {}), sleep.call_args_list)

    def test_confirmed_page_returns_normally(self):
        with (
            patch.object(travel, "click_change_btn"),
            patch.object(travel, "click_button"),
            patch.object(travel.run_control, "sleep"),
            patch.object(travel, "check_if_have_keyword", return_value=True),
            patch.object(travel.time, "monotonic", side_effect=[0, 0]),
        ):
            travel.change_location(Mock(), Mock(), FishingLocation.YANBO_LAKE)

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

    def test_stop_while_polling_propagates_without_timeout_recovery(self):
        task_control = control.RunControl()
        task_control.stopped.set()
        with (
            control.use_control(task_control),
            patch.object(travel, "click_change_btn"),
            patch.object(travel, "click_button"),
            patch.object(travel.run_control, "sleep"),
            patch.object(travel, "check_if_have_keyword") as check,
            patch.object(travel.time, "monotonic", return_value=0),
        ):
            with self.assertRaises(control.RunStopped):
                travel.change_location(Mock(), Mock(), FishingLocation.YANBO_LAKE)
            check.assert_not_called()
