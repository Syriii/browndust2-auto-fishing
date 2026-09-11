"""页面截图回放与入口分支验证；屏幕、输入和时钟全部替身，不操作游戏。"""

import configparser
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

import cv2
import numpy as np

from bd2_fishing.app.fishing_task import FishingBot
from bd2_fishing.game.fishing import actions, qte, recovery, settlement, startup
from bd2_fishing.game.fishing.scene import FishingSceneReader
from bd2_fishing.infrastructure.settings import DEFAULT_CONFIG_CONTENT
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect

FIXTURES = Path(__file__).parents[1] / "fixtures/catch_result"


def config():
    result = configparser.ConfigParser()
    result.read_string(DEFAULT_CONFIG_CONTENT)
    result.set("recovery", "page_wait_seconds", "0.6")
    result.set("time", "fish_end_wait_time", "0.4")
    return result


def load(name):
    return cv2.imread(str(FIXTURES / name))


class SceneTests(unittest.TestCase):
    def test_user_waiting_and_before_cast_are_different_regardless_of_character(self):
        for name, expected in (
            ("waiting_bite_user_20260911.png", "waiting"),
            ("idle_back_user_20260911.png", "idle"),
            # 正面图边缘裁切更多，坐标不完整时允许拒识，不能误判为等待。
            ("idle_front_user_20260911.png", "unrecognized"),
        ):
            frame = load(name)
            h, w = frame.shape[:2]
            reader = FishingSceneReader(config(), Rect(0, 0, w, h))
            self.assertEqual(reader.inspect(frame).state, expected, name)

    def test_real_pages_and_transition_remain_distinct(self):
        reader = FishingSceneReader(config(), Rect(57, 93, 1002, 625))
        for name, state, kind in (
            ("idle_day_945_180022.png", "idle", None),
            ("idle_no_arrows_holdout_20260910.png", "waiting", None),
            ("caught_close_holdout_945.png", "panel", "result"),
            ("level_up_holdout_20260910.png", "panel", "level_up"),
            ("loading_945.png", "unrecognized", None),
            ("idle_day_transition_180018.png", "unrecognized", None),
            ("qte_scene_night_01.png", "qte", None),
            ("qte_scene_night_10.png", "qte", None),
        ):
            with self.subTest(name=name):
                reading = reader.inspect(load(name))
                self.assertEqual((reading.state, reading.panel_kind), (state, kind))

    def test_missing_frames_blank_frames_and_incomplete_qte_cannot_authorize_entry(self):
        reader = FishingSceneReader(config(), Rect(0, 0, 945, 532))
        self.assertEqual(reader.inspect(None).state, "unavailable")
        self.assertEqual(reader.inspect(np.zeros((20, 20, 3), np.uint8)).state, "unavailable")
        for value in (0, 190, 255):
            self.assertEqual(
                reader.inspect(np.full((532, 945, 3), value, np.uint8)).state, "unrecognized"
            )
        frame = load("qte_scene_night_01.png")
        timer = reader.idle.time_region
        frame[timer.top : timer.bottom, timer.left : timer.right] = 0
        self.assertEqual(reader.inspect(frame).state, "unrecognized")


class StartupTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(
            patch.object(startup.paths, "get_diagnostics_path", return_value=str(self.directory))
        )
        self.observer = settlement.CatchObserver(None, config(), Rect(0, 0, 945, 532))
        stack.enter_context(patch.object(startup, "CatchObserver", return_value=self.observer))
        capture = stack.enter_context(patch.object(settlement, "FeedbackCapture"))
        self.camera = capture.return_value.__enter__.return_value
        self.frames = [load("idle_day_945_180022.png")]
        self.stage = 0
        self.camera.grab.side_effect = lambda: self.frames[self.stage]
        self.guard = stack.enter_context(patch.object(settlement.window, "WindowGuard"))
        self.input = stack.enter_context(patch.object(recovery, "game_input"))
        self.input.click.side_effect = self.advance
        self.clock = 0.0
        stack.enter_context(patch.object(control, "sleep", side_effect=self.sleep))
        stack.enter_context(patch.object(startup.time, "monotonic", side_effect=lambda: self.clock))

    def sleep(self, seconds):
        self.clock += seconds

    def advance(self, *_):
        self.stage = min(self.stage + 1, len(self.frames) - 1)

    def run_entry(self):
        return startup.prepare_start(self.observer.config, self.observer.window)

    def evidence(self):
        with ZipFile(next(self.directory.rglob("*.zip"))) as archive:
            return json.loads(archive.read("metadata.json")), archive.namelist()

    def test_idle_needs_separated_observations_and_no_input(self):
        self.assertEqual(self.run_entry(), "idle")
        self.assertGreaterEqual(self.clock, 0.19)
        self.input.click.assert_not_called()
        self.assertEqual(list(self.directory.rglob("*.zip")), [])

    def test_waiting_entry_does_not_authorize_cast(self):
        self.frames = [load("idle_no_arrows_holdout_20260910.png")]
        self.assertEqual(self.run_entry(), "waiting")
        self.input.click.assert_not_called()

    def test_existing_bite_only_presses_once_on_confirmed_waiting_page(self):
        self.frames = [load("idle_no_arrows_holdout_20260910.png")]
        # 合成咬钩检测结果只验证路由；不冒充真实前后连续截图。
        with (
            patch.object(startup, "HookReader") as hook,
            patch.object(startup, "game_input") as inputs,
        ):
            hook.return_value.inspect.return_value = (True, 300)
            state = startup.resume_waiting_for_bite(self.observer.config, self.observer.window)
        self.assertEqual(state, "hooked")
        inputs.press.assert_called_once_with("space")
        self.input.click.assert_not_called()

    def test_existing_waiting_timeout_or_unknown_never_blindly_recasts(self):
        for name in ("idle_no_arrows_holdout_20260910.png", "loading_945.png"):
            self.frames = [load(name)]
            with (
                patch.object(startup, "BITE_TIMEOUT_SECONDS", 0.4),
                patch.object(startup, "game_input") as inputs,
            ):
                with self.assertRaisesRegex(recovery.RoundObservationError, "接续等待咬钩超时"):
                    startup.resume_waiting_for_bite(self.observer.config, self.observer.window)
            inputs.press.assert_not_called()
            self.input.click.assert_not_called()

    def test_existing_bite_on_qte_or_unknown_does_not_send_hook_press(self):
        self.frames = [load("qte_scene_night_01.png")]
        with (
            patch.object(startup, "HookReader") as hook,
            patch.object(startup, "game_input") as inputs,
        ):
            hook.return_value.inspect.return_value = (True, 300)
            self.assertEqual(
                startup.resume_waiting_for_bite(self.observer.config, self.observer.window), "qte"
            )
        inputs.press.assert_not_called()
        hook.return_value.inspect.assert_not_called()

    def test_waiting_can_return_to_idle_without_pressing(self):
        with patch.object(startup, "game_input") as inputs:
            self.assertEqual(
                startup.resume_waiting_for_bite(self.observer.config, self.observer.window), "idle"
            )
        inputs.press.assert_not_called()

    def test_qte_can_be_resumed_without_click_or_waiting_full_timeout(self):
        self.frames = [load("qte_scene_night_01.png")]
        self.assertEqual(self.run_entry(), "qte")
        self.assertGreaterEqual(self.clock, 0.049)
        self.assertLess(self.clock, 0.2)
        self.input.click.assert_not_called()

    def test_qte_that_ends_after_entry_goes_to_settlement_without_loading_timeout(self):
        strategy = qte.FrostStraitQTEStrategy(config(), self.observer.window)
        strategy.catch_observer = self.observer
        self.observer.evidence_metadata["resumed_qte"] = True
        strategy._qte_trace = Mock()
        strategy._finish_fishing = Mock()
        strategy._grab_qte_frames = Mock(return_value=np.zeros((42, 312, 3), np.uint8))
        strategy._on_control_timeout = Mock(side_effect=AssertionError("不应等待加载超时"))
        with patch.object(qte, "pydirectinput") as inputs:
            qte.BaseQTEStrategy.play_qte.__wrapped__(strategy, Mock())
        strategy._finish_fishing.assert_called_once()
        inputs.press_qte.assert_not_called()
        self.assertLess(self.clock, 2)

    def test_reward_then_upgrade_then_idle_saved_separately_from_fish_counts(self):
        self.frames = [
            load("caught_945.png"),
            load("level_up_holdout_20260910.png"),
            self.frames[0],
        ]
        self.assertEqual(self.run_entry(), "idle")
        self.assertEqual(self.input.click.call_count, 2)
        metadata, names = self.evidence()
        self.assertEqual(metadata["event"], "startup_prepared")
        self.assertTrue(metadata["evidence_id"])
        self.assertEqual(metadata["closed_panel_kinds"], ["result", "level_up"])
        self.assertNotIn("result", metadata)
        self.assertIn("panel_before_level_up.png", names)

    def test_unknown_is_observed_without_click_and_evidence_preserved(self):
        self.frames = [load("loading_945.png")]
        with self.assertRaisesRegex(recovery.RoundObservationError, "未确认当前页面"):
            self.run_entry()
        self.input.click.assert_not_called()
        metadata, names = self.evidence()
        self.assertEqual(metadata["startup"]["status"], "failed")
        self.assertIn("resume_latest.png", names)

    def test_stuck_upgrade_does_not_repeat_click(self):
        self.frames = [load("level_up_holdout_20260910.png")]
        with self.assertRaises(recovery.RoundObservationError):
            self.run_entry()
        self.input.click.assert_called_once()

    def test_page_change_before_click_does_not_authorize_input(self):
        self.frames = [load("caught_945.png"), load("loading_945.png")]
        self.input.moveTo.side_effect = self.advance
        with self.assertRaises(recovery.RoundObservationError):
            self.run_entry()
        self.input.click.assert_not_called()

    def test_focus_loss_propagates_without_input_or_new_capture(self):
        self.guard.return_value.side_effect = control.RunStopped("失焦")
        with self.assertRaisesRegex(control.RunStopped, "失焦"):
            self.run_entry()
        self.camera.grab.assert_not_called()
        self.input.click.assert_not_called()
        metadata, _ = self.evidence()
        self.assertFalse(metadata["screenshots_available"])

    def test_unknown_transition_can_settle_before_timeout(self):
        self.camera.grab.side_effect = lambda: (
            load("loading_945.png") if self.clock < 0.1 else self.frames[0]
        )
        self.assertEqual(self.run_entry(), "idle")
        self.input.click.assert_not_called()


class EntryRoutingTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        capture = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
        self.bot = FishingBot(
            config(), Rect(0, 0, 945, 532), Mock(), capture_factory=lambda **kw: capture
        )
        self.bot.choose_strategy = Mock()
        self.bot.wait_for_bite = Mock()
        self.bot.should_change_location = Mock(return_value=False)
        stack.enter_context(patch("bd2_fishing.app.fishing_task.window.WindowGuard"))
        stack.enter_context(patch.object(control, "sleep"))
        self.entry = stack.enter_context(
            patch.object(startup, "prepare_start", return_value="idle")
        )
        self.ready = stack.enter_context(patch.object(settlement, "confirm_ready_for_next_cast"))
        stack.enter_context(
            patch.object(settlement, "CatchObserver", return_value=Mock(evidence_metadata={}))
        )
        self.play = stack.enter_context(
            patch.object(settlement, "run_observed_qte", side_effect=control.RunStopped("done"))
        )
        self.cast = stack.enter_context(patch.object(actions, "cast_rod"))

    def test_qte_entry_bypasses_cast_bite_and_location_changes(self):
        self.entry.return_value = "qte"
        with self.assertRaises(control.RunStopped):
            self.bot.run()
        self.cast.assert_not_called()
        self.bot.wait_for_bite.assert_not_called()
        self.bot.should_change_location.assert_not_called()
        self.play.assert_called_once()
        self.assertTrue(
            self.bot.choose_strategy.return_value.catch_observer.evidence_metadata["resumed_qte"]
        )

    def test_unknown_start_cannot_cast_or_change_location(self):
        self.entry.side_effect = recovery.RoundObservationError("unknown")
        with self.assertRaises(recovery.RoundObservationError):
            self.bot.run()
        self.cast.assert_not_called()
        self.bot.should_change_location.assert_not_called()
        self.play.assert_not_called()

    def test_waiting_entry_skips_cast_and_uses_single_existing_bite_observation(self):
        self.entry.return_value = "waiting"
        with patch.object(startup, "resume_waiting_for_bite", return_value="hooked") as resume:
            with self.assertRaises(control.RunStopped):
                self.bot.run()
        resume.assert_called_once()
        self.cast.assert_not_called()
        self.bot.wait_for_bite.assert_not_called()
        self.bot.should_change_location.assert_not_called()
        self.play.assert_called_once()

    def test_recovery_waiting_handoff_skips_round_delay_and_second_cast(self):
        self.play.side_effect = ["waiting", control.RunStopped("done")]
        with (
            patch.object(startup, "resume_waiting_for_bite", return_value="hooked") as resume,
            patch.object(control, "sleep") as sleep,
        ):
            with self.assertRaises(control.RunStopped):
                self.bot.run()
        resume.assert_called_once()
        self.cast.assert_called_once()
        self.bot.wait_for_bite.assert_called_once()
        self.assertEqual(self.play.call_count, 2)
        # 唯一等待是启动配置的等待，不插入轮间 4 秒耽误咬钩。
        sleep.assert_called_once_with(self.bot.begin_fish_wait_time)

    def test_first_cast_requires_fresh_idle_after_startup(self):
        self.ready.side_effect = recovery.RoundObservationError("changed")
        with self.assertRaises(recovery.RoundObservationError):
            self.bot.run()
        self.cast.assert_not_called()
        self.bot.should_change_location.assert_not_called()

    def test_regular_bite_timeout_rechecks_page_instead_of_blind_recovery(self):
        self.entry.return_value = "waiting"
        with (
            patch.object(startup, "resume_waiting_for_bite", return_value="hooked"),
            patch.object(actions, "recover_from_timeout") as old_recovery,
        ):
            self.assertTrue(self.bot._recover_bite_timeout())
        self.cast.assert_not_called()
        old_recovery.assert_not_called()
        self.entry.return_value = "qte"
        self.assertEqual(self.bot._recover_bite_timeout(), "qte")

    def test_regular_timeout_recast_requires_confirmed_idle(self):
        self.assertFalse(self.bot._recover_bite_timeout())
        self.ready.assert_called_once()
        self.cast.assert_called_once()

    def test_regular_timeout_unknown_page_cannot_send_input(self):
        self.entry.side_effect = recovery.RoundObservationError("unknown")
        with self.assertRaises(recovery.RoundObservationError):
            self.bot._recover_bite_timeout()
        self.cast.assert_not_called()
