"""用户原图的真实 OCR 回归，以及导航输入边界；不连接游戏。"""

from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2
import numpy as np

from bd2_fishing.app.ocr_setup import build_ocr_engine
from bd2_fishing.game.fishing.scene import FishingSceneReader
from bd2_fishing.game.navigation.voyage import NavigationFailed, VoyageNavigator
from bd2_fishing.game.navigation.voyage_reading import IslandMarker, VoyageReader, VoyageReading
from bd2_fishing.infrastructure import settings
from bd2_fishing.runtime.control import RunStopped
from bd2_fishing.runtime.geometry import Rect

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/voyage_pages"


class VoyageImageTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = settings.read_ini(str(ROOT / "bd2_fishing/resources/default.ini"))
        cls.reader = VoyageReader(build_ocr_engine(cls.config))
        cls.readings = {}
        for path in FIXTURES.glob("*.png"):
            cls.readings[path.name] = cls.reader.inspect(cv2.imread(str(path))[31:563, 1:946])

    def test_loading_and_dock(self):
        self.assertEqual(self.readings["01_loading.png"].page, "loading")
        dock = self.readings["02_dock.png"]
        self.assertEqual((dock.page, dock.action, dock.player_level), ("dock", "start_fishing", 26))

    def test_real_button_bounds_contain_their_confirmed_points(self):
        for reading in self.readings.values():
            if reading.action in {"start_fishing", "sail", "purchase_license"}:
                self.assertIsNotNone(reading.action_bounds)
                left, top, right, bottom = reading.action_bounds
                x, y = reading.action_point
                self.assertTrue(0 <= left <= x < right <= 945)
                self.assertTrue(0 <= top <= y < bottom <= 532)

    def test_selected_islands(self):
        for name, island in [
            ("03_map_yanbo.png", "烟波湖"),
            ("04_map_shallow_panned.png", "浅岸"),
            ("05_sky_before_license.png", "天空岛"),
            ("06_sky_after_license.png", "天空岛"),
            ("07_atlantis_fish_unlocks.png", "亚特兰蒂斯"),
        ]:
            with self.subTest(name=name):
                result = self.readings[name]
                self.assertEqual((result.page, result.island), ("map", island))
                self.assertTrue(any(marker.selected for marker in result.markers))

    def test_license_and_level_are_independent(self):
        before = self.readings["05_sky_before_license.png"]
        after = self.readings["06_sky_after_license.png"]
        self.assertEqual((before.action, before.license_state), ("purchase_license", "required"))
        self.assertEqual((after.action, after.license_state), ("sail", "available"))
        for result in (before, after):
            self.assertEqual(result.recommended_level, 31)
            self.assertIs(result.level_warning, True)

    def test_fish_and_empty_slots(self):
        fish = self.readings["07_atlantis_fish_unlocks.png"].fish
        self.assertEqual(fish, ("unlocked",) * 13 + ("locked",) * 2)
        sky = self.readings["06_sky_after_license.png"].fish
        self.assertEqual(sky, ("locked",) * 13 + ("empty",) * 2)
        self.assertEqual(self.readings["03_map_yanbo.png"].fish[-1], "empty")

    def test_real_fishing_and_blank_are_not_navigation(self):
        for name in [
            "waiting_bite_user_20260911.png",
            "idle_back_user_20260911.png",
            "qte_scene_night_01.png",
            "level_up_source_20260910.png",
        ]:
            with self.subTest(name=name):
                frame = cv2.imread(str(ROOT / "tests/fixtures/catch_result" / name))
                self.assertIn(self.reader.inspect(frame).page, ("unknown", "island"))
        self.assertEqual(
            VoyageReader(None).inspect(np.zeros((532, 945, 3), np.uint8)).page, "unknown"
        )

    def test_return_confirmation_blocks_fishing_and_exposes_confirm_point(self):
        frame = cv2.imread(str(FIXTURES / "controls/return_to_dock_confirmation.png"))
        height, width = frame.shape[:2]
        scene = FishingSceneReader(self.config, Rect(0, 0, width, height)).inspect(frame)
        self.assertEqual(scene.state, "blocked_dialog")
        self.assertEqual(scene.panel_kind, "return_to_dock")
        voyage = self.reader.inspect(frame)
        self.assertEqual(voyage.page, "return_confirmation")
        self.assertEqual(voyage.action, "confirm_return")
        self.assertIsNotNone(voyage.action_point)

    def test_change_control_is_read_from_user_image(self):
        frame = cv2.imread(str(FIXTURES / "controls/island_navigation_controls.png"))
        reading = self.reader.inspect(frame)
        self.assertEqual(
            (reading.page, reading.island, reading.action),
            ("island", "亚特兰蒂斯", "change_island"),
        )
        self.assertLess(reading.action_point[0], 270)

    def test_travel_confirmation_images_identify_destination_and_button(self):
        for name in ("travel_consumables_confirmation.png", "travel_confirmation_user.png"):
            with self.subTest(name=name):
                frame = cv2.imread(str(FIXTURES / "controls" / name))
                reading = self.reader.inspect(frame)
                self.assertEqual(
                    (reading.page, reading.island, reading.action),
                    ("travel_confirmation", "深渊巨口", "confirm_travel"),
                )
                self.assertTrue(400 < reading.action_point[0] < 550)
                if name == "travel_consumables_confirmation.png":
                    scene = FishingSceneReader(self.config, Rect(0, 0, 945, 532)).inspect(frame)
                    self.assertEqual(
                        (scene.state, scene.panel_kind), ("blocked_dialog", "travel_confirmation")
                    )

    def test_unreadable_origin_does_not_hide_verified_change_control(self):
        frame = cv2.imread(str(FIXTURES / "controls/island_day_name_unreadable.png"))
        reading = self.reader.inspect(frame)
        self.assertEqual((reading.page, reading.action), ("island", "change_island"))
        self.assertIsNone(reading.island)
        scene = FishingSceneReader(self.config, Rect(0, 0, 945, 532)).inspect(frame)
        self.assertEqual(scene.state, "idle")


class NavigationPolicyTests(TestCase):
    def setUp(self):
        config = settings.read_ini(str(ROOT / "bd2_fishing/resources/default.ini"))
        self.nav = VoyageNavigator(config, Rect(1941, 534, 2886, 1066), None, "亚特兰蒂斯")
        self.nav.guard = Mock()
        self.frame = np.zeros((532, 945, 3), np.uint8)
        self.map = VoyageReading(
            page="map",
            action="sail",
            action_point=(814, 502),
            island="亚特兰蒂斯",
            license_state="available",
        )

    def test_purchase_button_never_clicked(self):
        reading = replace(self.map, action="purchase_license", license_state="required")
        with patch("bd2_fishing.game.navigation.voyage.game_input.click") as click:
            with self.assertRaises(NavigationFailed):
                self.nav.act(reading, self.frame)
            click.assert_not_called()

    def test_confirmed_button_uses_its_own_bounds_and_logs_actual_screen_point(self):
        reading = replace(self.map, action_bounds=(800, 492, 830, 514))
        with patch("bd2_fishing.game.navigation.voyage.game_input.click") as click:
            self.nav.act(reading, self.frame)
        (x, y), kwargs = click.call_args
        self.assertFalse(kwargs)
        self.assertTrue(2747 <= x < 2765)
        self.assertTrue(1031 <= y < 1043)
        self.assertEqual(self.nav.details["actions"][-1]["click_point"], (x, y))

    def test_malformed_button_bounds_do_not_fall_back_to_point_click(self):
        for bounds in ((850, 492, 870, 514), (800, 492, 950, 514), (800, 510, 830, 505)):
            with patch("bd2_fishing.game.navigation.voyage.game_input.click") as click:
                with self.assertRaises(NavigationFailed):
                    self.nav.act(replace(self.map, action_bounds=bounds), self.frame)
                click.assert_not_called()

    def test_return_dialog_is_blocked_without_input(self):
        self.nav.observe = Mock(
            return_value=(self.frame, VoyageReading(page="return_confirmation"))
        )
        with patch("bd2_fishing.game.navigation.voyage.game_input.click") as click:
            with self.assertRaisesRegex(NavigationFailed, "返回码头"):
                self.nav.run(Mock())
            click.assert_not_called()
            self.assertTrue(self.nav.active)

    def test_change_requires_explicit_mode_and_confirmed_idle(self):
        island = VoyageReading(
            page="island", island="亚特兰蒂斯", action="change_island", action_point=(210, 50)
        )
        with patch("bd2_fishing.game.navigation.voyage.game_input.click") as click:
            with self.assertRaises(NavigationFailed):
                self.nav.act(island, self.frame)
            click.assert_not_called()
            self.nav.change_from_island = True
            with self.assertRaises(NavigationFailed):
                self.nav.act(replace(island, action=None), self.frame)
            click.assert_not_called()
            self.nav.act(island, self.frame)
            click.assert_called_once_with(2151, 584)
            self.assertEqual(self.nav.pending[0], "change_island")

    def test_dialog_has_priority_over_idle_background(self):
        self.nav.fishing.inspect = Mock(
            return_value=Mock(state="blocked_dialog", panel_kind="return_to_dock")
        )
        camera = Mock()
        camera.grab.return_value = self.frame
        self.nav.reader.inspect = Mock()
        _, reading = self.nav.observe(camera)
        self.assertEqual(reading.page, "return_confirmation")
        self.nav.reader.inspect.assert_not_called()

    def test_travel_confirmation_without_destination_stops(self):
        self.nav.pending = ("sail", "深渊巨口", 0)
        self.nav.observe = Mock(
            return_value=(self.frame, VoyageReading(page="travel_confirmation"))
        )
        with patch("bd2_fishing.game.navigation.voyage.game_input.click") as click:
            with (
                patch("bd2_fishing.game.navigation.voyage.control.sleep"),
                self.assertRaisesRegex(NavigationFailed, "目的地"),
            ):
                self.nav.run(Mock())
            click.assert_not_called()

    def test_travel_confirmation_only_once_for_matching_target(self):
        popup = VoyageReading(
            page="travel_confirmation",
            island="亚特兰蒂斯",
            action="confirm_travel",
            action_point=(475, 318),
        )
        self.nav.observe = Mock(side_effect=[(self.frame, r) for r in (popup, popup, "idle")])
        with (
            patch("bd2_fishing.game.navigation.voyage.game_input.click") as click,
            patch("bd2_fishing.game.navigation.voyage.control.sleep"),
        ):
            self.assertEqual(str(self.nav.run(Mock())), "亚特兰蒂斯")
            click.assert_called_once_with(2416, 852)

    def test_wrong_destination_or_disabled_confirmation_does_not_click(self):
        popup = VoyageReading(
            page="travel_confirmation",
            island="深渊巨口",
            action="confirm_travel",
            action_point=(475, 318),
        )
        with patch("bd2_fishing.game.navigation.voyage.game_input.click") as click:
            with self.assertRaises(NavigationFailed):
                self.nav.act(popup, self.frame)
            if not self.nav.config.has_section("navigation"):
                self.nav.config.add_section("navigation")
            self.nav.config.set("navigation", "confirm_island_change", "false")
            with self.assertRaises(NavigationFailed):
                self.nav.act(replace(popup, island="亚特兰蒂斯"), self.frame)
            click.assert_not_called()

    def test_confirmed_travel_waits_without_repeated_clicks(self):
        popup = VoyageReading(
            page="travel_confirmation",
            island="亚特兰蒂斯",
            action="confirm_travel",
            action_point=(475, 318),
        )
        with (
            patch("bd2_fishing.game.navigation.voyage.time.monotonic", return_value=10),
            patch("bd2_fishing.game.navigation.voyage.game_input.click") as click,
        ):
            self.nav.act(popup, self.frame)
            for _ in range(3):
                self.assertTrue(self.nav._waiting_for_transition(popup))
            click.assert_called_once()
        with patch("bd2_fishing.game.navigation.voyage.time.monotonic", return_value=51):
            with self.assertRaises(NavigationFailed):
                self.nav._waiting_for_transition(popup)

    def test_red_level_is_not_license_block(self):
        with patch("bd2_fishing.game.navigation.voyage.game_input.click") as click:
            self.nav.act(replace(self.map, level_warning=True), self.frame)
            click.assert_called_once_with(2755, 1036)
            self.assertEqual(self.nav.pending[0], "sail")

    def test_wrong_selected_island_never_sails(self):
        with patch("bd2_fishing.game.navigation.voyage.game_input.click") as click:
            self.nav.act(
                replace(self.map, island="烟波湖", markers=(IslandMarker(200, 250, False),)),
                self.frame,
            )
            click.assert_called_once_with(2141, 784)
            self.assertEqual(self.nav.pending[0], "select_island")

    def test_unconfirmed_action_does_not_repeat(self):
        self.nav.pending = ("sail", "亚特兰蒂斯", 0)
        with patch("bd2_fishing.game.navigation.voyage.time.monotonic", return_value=41):
            with self.assertRaises(NavigationFailed):
                self.nav._waiting_for_transition(self.map)

    def test_stop_before_click_propagates(self):
        self.nav.guard.side_effect = RunStopped("stopped")
        with patch("bd2_fishing.game.navigation.voyage.game_input.click") as click:
            with self.assertRaises(RunStopped):
                self.nav.act(self.map, self.frame)
            click.assert_not_called()

    def test_unknown_button_does_not_click(self):
        with patch("bd2_fishing.game.navigation.voyage.game_input.click") as click:
            with self.assertRaises(NavigationFailed):
                self.nav.act(replace(self.map, action=None), self.frame)
            click.assert_not_called()

    def test_map_search_is_bounded(self):
        self.nav.pans = 2
        with self.assertRaises(NavigationFailed):
            self.nav.act(replace(self.map, island="烟波湖"), self.frame)

    def test_fishing_page_passes_through_without_navigation(self):
        self.nav.observe = Mock(return_value=(self.frame, "waiting"))
        self.assertIsNone(self.nav.run(Mock()))
        self.assertEqual(self.nav.details["actions"], [])

    def test_explicit_change_does_not_treat_waiting_as_success(self):
        nav = VoyageNavigator(
            self.nav.config, self.nav.region, None, "烟波湖", change_from_island=True
        )
        nav.observe = Mock(return_value=(self.frame, "waiting"))
        with self.assertRaises(NavigationFailed):
            nav.run(Mock())
        self.assertTrue(nav.active)
        self.assertEqual(nav.details["actions"], [])

    def test_start_map_arrival_chain(self):
        dock = VoyageReading(page="dock", action="start_fishing", action_point=(865, 502))
        self.nav.observe = Mock(
            side_effect=[(self.frame, r) for r in (dock, dock, self.map, self.map, "idle")]
        )
        with (
            patch("bd2_fishing.game.navigation.voyage.game_input.click") as click,
            patch("bd2_fishing.game.navigation.voyage.control.sleep"),
        ):
            self.assertEqual(str(self.nav.run(Mock())), "亚特兰蒂斯")
            self.assertEqual(click.call_count, 2)
            self.assertEqual(self.nav.details["status"], "arrived")
