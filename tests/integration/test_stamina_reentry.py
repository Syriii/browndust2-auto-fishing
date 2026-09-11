"""150402 原图识别及退出重进的输入边界；不连接游戏。"""

from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

import cv2
import numpy as np

from bd2_fishing.app.ocr_setup import build_ocr_engine
from bd2_fishing.game.fishing import recovery
from bd2_fishing.game.fishing.dialogs import FishingDialogReader
from bd2_fishing.game.fishing.scene import SceneReading
from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.game.navigation import reentry
from bd2_fishing.game.navigation.voyage_reading import VoyageReading
from bd2_fishing.infrastructure import settings
from bd2_fishing.perception.ocr_types import OCRText
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/voyage_pages"


class StaminaImageTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = settings.read_ini(str(ROOT / "bd2_fishing/resources/default.ini"))
        cls.engine = build_ocr_engine(cls.config)

    def test_exact_error_and_holdout_allow_only_close_stage(self):
        worker = reentry.StaminaReentry(
            self.config, Rect(0, 0, 945, 532), self.engine, "亚特兰蒂斯", {}, {}
        )
        for name in ("stamina_150402.png", "stamina_150402_holdout.png"):
            with self.subTest(name=name):
                frame = cv2.imread(str(FIXTURES / "errors" / name))
                self.assertEqual(worker.read_stage(frame, "error"), (472, 292))
                self.assertEqual(worker.button_bounds, (458, 282, 489, 301))
                self.assertIsNone(worker.read_stage(frame, "closed"))
                self.assertIsNone(worker.button_bounds)

    def test_other_real_pages_are_not_stamina_error(self):
        reader = FishingDialogReader()
        for path in [*FIXTURES.glob("*.png"), *FIXTURES.glob("controls/*.png")]:
            with self.subTest(path=path.name):
                frame = cv2.imread(str(path))
                self.assertNotEqual(reader.inspect(frame)[0], "stamina_error")
        self.assertIsNone(reader.inspect(np.zeros((532, 945, 3), dtype=np.uint8))[0])

    def test_user_return_dialog_matches_reentry_confirmation_only(self):
        frame = cv2.imread(str(FIXTURES / "controls/return_to_dock_user_holdout.png"))
        height, width = frame.shape[:2]
        worker = reentry.StaminaReentry(
            self.config, Rect(0, 0, width, height), self.engine, "亚特兰蒂斯", {}, {}
        )
        self.assertEqual(worker.fishing.inspect(frame).panel_kind, "return_to_dock")
        point = worker.read_stage(frame, "return")
        self.assertIsNotNone(point)
        self.assertIsNotNone(worker.button_bounds)
        self.assertTrue(470 < point[0] < 590 and 290 < point[1] < 345)
        self.assertIsNone(worker.read_stage(frame, "error"))
        self.assertIsNone(worker.read_stage(frame, "closed"))


class StaminaReentryTests(TestCase):
    def setUp(self):
        self.worker = reentry.StaminaReentry(
            settings.read_ini(str(ROOT / "bd2_fishing/resources/default.ini")),
            Rect(1920, 400, 2865, 932),
            Mock(),
            "亚特兰蒂斯",
            {},
            {},
        )
        self.worker.guard = Mock()
        self.camera = Mock()
        self.camera.__enter__ = Mock(return_value=self.camera)
        self.camera.__exit__ = Mock(return_value=False)
        for target, value in [
            ("FeedbackCapture", Mock(return_value=self.camera)),
            ("game_input", Mock()),
            ("prepare_voyage", Mock(return_value=FishingLocation("亚特兰蒂斯"))),
        ]:
            p = patch.object(reentry, target, value)
            setattr(self, target, p.start())
            self.addCleanup(p.stop)
        p = patch.object(control, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def test_complete_sequence_returns_to_original_island(self):
        self.worker.wait = Mock(side_effect=[(472, 292), ("island",), (523, 315), ("dock",)])
        self.worker.run()
        self.assertEqual(
            self.game_input.mock_calls,
            [call.click(2392, 692), call.press("esc"), call.click(2443, 715)],
        )
        self.assertEqual(
            [x.args[1] for x in self.worker.wait.call_args_list],
            ["error", "closed", "return", "dock"],
        )
        self.prepare_voyage.assert_called_once_with(
            self.worker.config, self.worker.region, self.worker.engine, self.worker.origin
        )

    def test_close_must_disappear_before_escape(self):
        self.worker.wait = Mock(side_effect=[(472, 292), reentry.NavigationFailed("still error")])
        with self.assertRaises(reentry.NavigationFailed):
            self.worker.run()
        self.game_input.click.assert_called_once()
        self.game_input.press.assert_not_called()
        self.prepare_voyage.assert_not_called()

    def test_missing_return_confirmation_does_not_click_again(self):
        self.worker.wait = Mock(
            side_effect=[(472, 292), ("island",), reentry.NavigationFailed("unknown dialog")]
        )
        with self.assertRaises(reentry.NavigationFailed):
            self.worker.run()
        self.game_input.click.assert_called_once()
        self.game_input.press.assert_called_once_with("esc")
        self.prepare_voyage.assert_not_called()

    def test_mismatched_arrival_is_not_success(self):
        self.worker.wait = Mock(side_effect=[(472, 292), ("island",), (523, 315), ("dock",)])
        self.prepare_voyage.return_value = FishingLocation("烟波湖")
        with self.assertRaisesRegex(reentry.NavigationFailed, "原钓场"):
            self.worker.run()

    def test_focus_failure_before_action_propagates(self):
        self.worker.wait = Mock(return_value=(472, 292))
        self.worker.guard.side_effect = control.RunStopped("focus")
        with self.assertRaises(control.RunStopped):
            self.worker.run()
        self.assertEqual(self.game_input.mock_calls, [])

    def test_reentry_random_click_records_point_and_rejects_mismatched_bounds(self):
        self.worker.button_bounds = (458, 282, 489, 301)
        self.game_input.click_in_rect.return_value = (2391, 691)
        self.worker.click((472, 292), "close_150402")
        self.game_input.click_in_rect.assert_called_once_with(Rect(2378, 682, 2409, 701))
        self.assertEqual(self.worker.details["actions"][-1]["click_point"], (2391, 691))
        self.game_input.reset_mock()
        with self.assertRaises(reentry.NavigationFailed):
            self.worker.click((523, 315), "return_to_dock")
        self.assertEqual(self.game_input.mock_calls, [])

    def test_unknown_pages_exhaust_bounded_wait_without_input(self):
        self.worker.read_stage = Mock(return_value=None)
        with self.assertRaises(reentry.NavigationFailed):
            self.worker.run()
        self.assertEqual(self.camera.grab.call_count, 81)
        self.assertEqual(self.game_input.mock_calls, [])

    def test_single_matching_frame_is_insufficient(self):
        self.worker.read_stage = Mock(side_effect=[(472, 292)] + [None] * 80)
        with self.assertRaises(reentry.NavigationFailed):
            self.worker.run()
        self.assertEqual(self.game_input.mock_calls, [])

    def test_similar_dialog_with_different_code_is_rejected(self):
        self.worker.fishing = Mock(
            inspect=Mock(return_value=SceneReading("blocked_dialog", panel_kind="stamina_error"))
        )
        for code in ("150403", "1504021", "150402"):
            self.worker.voyage = Mock(
                inspect=Mock(return_value=VoyageReading(texts=(OCRText("error:" + code, 0.99),)))
            )
            result = self.worker.read_stage(Mock(), "error")
            self.assertEqual(result is not None, code == "150402")

    def test_no_origin_or_ocr_prevents_any_action(self):
        for origin, engine in ((None, Mock()), ("天空岛", Mock()), ("亚特兰蒂斯", None)):
            with self.assertRaises(reentry.NavigationFailed):
                reentry.StaminaReentry(Mock(), self.worker.region, engine, origin, {}, {})
        self.assertEqual(self.game_input.mock_calls, [])

    def test_round_recovery_dispatches_only_stamina_error(self):
        observer = SimpleNamespace(
            evidence_metadata={"resume_check": {"panel_kind": "stamina_error"}},
            inspect_current_page=Mock(return_value="blocked_dialog"),
        )
        config = settings.read_ini(str(ROOT / "bd2_fishing/resources/default.ini"))
        config.set("recovery", "page_wait_seconds", "0")
        strategy = SimpleNamespace(_feedback_config=config)
        details = {"samples": []}
        with patch.object(reentry, "reenter_after_stamina_error") as enter:
            recovery._wait_for_recovery(strategy, observer, details)
            enter.assert_called_once_with(observer)
        self.assertEqual(details["next_state"], "idle")
        observer.evidence_metadata["resume_check"]["panel_kind"] = "return_to_dock"
        with patch.object(reentry, "reenter_after_stamina_error") as enter:
            with self.assertRaises(recovery.RoundObservationError):
                recovery._wait_for_recovery(strategy, observer, {"samples": []})
            enter.assert_not_called()
