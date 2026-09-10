"""真实区域回放与绿色动作替身验证；不打开游戏、不发送系统输入。"""

import configparser
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from bd2_fishing.game.fishing import qte
from bd2_fishing.game.fishing.feedback import FeedbackSession
from bd2_fishing.game.fishing.mechanics.green_control import GreenHoldController
from bd2_fishing.game.fishing.mechanics.regions import (
    GreenTarget,
    MechanismRegions,
    read_mechanism_regions,
)
from bd2_fishing.infrastructure import settings
from bd2_fishing.infrastructure.windows import input as inputs
from bd2_fishing.runtime import control
from bd2_fishing.runtime.geometry import Rect

FIXTURES = Path(__file__).parents[1] / "fixtures/qte_control"


class MechanismImageTests(unittest.TestCase):
    def test_real_green_and_mixed_frames_block_guessing_an_entry(self):
        for name in ("green_mixed_000.png", "green_mixed_001.png", "green_only_058.png"):
            frame = cv2.imread(str(FIXTURES / name))[117:136, 86:330]
            reading = read_mechanism_regions(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
            self.assertTrue(reading.green_present, name)
            if reading.green is not None:
                self.assertIsNone(reading.green.entry)
            machine = GreenHoldController()
            for i in range(5):
                self.assertEqual(
                    machine.observe(reading.green, 120 + i, i * 0.02, present=True).action,
                    "wait",
                )

    def test_real_obstructions_are_local_and_normal_blue_is_not_green(self):
        for name, kind in (("red_teeth_11.png", "red"), ("purple_content.png", "purple")):
            frame = cv2.imread(str(FIXTURES / name))[21:40, 68:312]
            regions = read_mechanism_regions(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
            self.assertFalse(regions.green_present)
            self.assertTrue(getattr(regions, kind + "_spans"))
            self.assertTrue(regions.blocked.any())
            self.assertFalse(regions.blocked.all())
            mask = np.full(frame.shape[:2], 255, np.uint8)
            clean = regions.mask_target(mask)
            self.assertFalse(clean[:, regions.blocked].any())
            self.assertTrue(clean[:, ~regions.blocked].all())
        frame = cv2.imread(str(FIXTURES / "blue_only_0.png"))[21:40, 68:312]
        regions = read_mechanism_regions(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
        self.assertFalse(regions.green_present)
        self.assertFalse(regions.blocked.any())


class GreenStateTests(unittest.TestCase):
    target = GreenTarget(20, 80, (20, 30))

    def start_hold(self, machine=None):
        machine = machine or GreenHoldController()
        self.assertEqual(machine.observe(self.target, 15, 0, present=True).action, "wait")
        self.assertEqual(machine.observe(self.target, 24, 0.03, present=True).action, "down")
        return machine

    def test_left_and_right_entry_hold_then_release_once_inside(self):
        machine = self.start_hold()
        self.assertEqual(machine.observe(self.target, 28, 0.05, present=True).action, "wait")
        result = machine.observe(self.target, 40, 0.08, present=True)
        self.assertEqual((result.action, result.reason), ("up", "green_release_inside"))
        self.assertEqual(machine.observe(self.target, 24, 0.10, present=True).action, "wait")
        right = GreenTarget(20, 80, (70, 80))
        machine = GreenHoldController()
        machine.observe(right, 90, 0, present=True)
        self.assertEqual(machine.observe(right, 76, 0.03, present=True).action, "down")
        self.assertEqual(machine.observe(right, 60, 0.06, present=True).action, "up")

    def test_missing_pointer_obstacle_gap_changed_bar_and_reverse_release(self):
        for target, cursor, stamp, blocked in (
            (self.target, None, 0.05, False),
            (self.target, 26, 0.05, True),
            (self.target, 26, 0.3, False),
            (GreenTarget(25, 85, (25, 35)), 26, 0.05, False),
            (self.target, 23, 0.05, False),
            (self.target, 85, 0.05, False),
        ):
            machine = self.start_hold()
            self.assertEqual(
                machine.observe(target, cursor, stamp, present=True, blocked=blocked).action, "up"
            )
            self.assertFalse(machine.held)

    def test_hold_limit_stop_and_absence_do_not_rearm_on_one_bad_frame(self):
        machine = self.start_hold(GreenHoldController(max_hold=0.06))
        result = machine.observe(self.target, 26, 0.10, present=True)
        self.assertEqual(result.reason, "green_hold_limit")
        self.assertEqual(machine.observe(None, None, 0.12).action, "wait")
        self.assertEqual(machine.observe(self.target, 24, 0.14, present=True).action, "wait")
        machine.observe(None, None, 0.16)
        self.assertEqual(machine.observe(None, None, 0.18).action, "normal")
        machine = self.start_hold()
        self.assertEqual(machine.release("stop").action, "up")
        self.assertEqual(machine.release("stop").action, "wait")

    def test_missing_frame_and_time_gap_break_exit_confirmation(self):
        for invalidate in (True, False):
            machine = self.start_hold()
            machine.release("stop")
            machine.observe(None, None, 0.05)
            if invalidate:
                machine.invalidate_observation()
            stamp = 0.06 if invalidate else 0.3
            self.assertEqual(machine.observe(None, None, stamp).action, "wait")
            self.assertTrue(machine.consumed)
            self.assertEqual(machine.observe(None, None, stamp + 0.02).action, "normal")

    def test_release_near_far_edge_or_nonincreasing_time_is_not_success(self):
        for cursor, stamp, present in ((79, 0.06, True), (26, 0.03, True), (26, 0.06, False)):
            machine = self.start_hold()
            result = machine.observe(self.target, cursor, stamp, present=present)
            self.assertEqual(result.action, "up")
            self.assertNotEqual(result.reason, "green_release_inside")

    def test_ordinary_frames_and_capture_gaps_do_not_enter_green_exit_mode(self):
        machine = GreenHoldController()
        for stamp in (0, 0, 0.2, 1):
            machine.invalidate_observation()
            self.assertEqual(machine.observe(None, 50, stamp).action, "normal")


class GreenIntegrationTests(unittest.TestCase):
    def make_strategy(self, cls):
        config = configparser.ConfigParser()
        config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        strategy = cls(config, Rect(0, 0, 945, 532))
        strategy._start_feedback = Mock()
        strategy._press_qte = Mock()
        strategy._time_bar_visible_from_masks = Mock(return_value=True)
        return strategy

    def test_both_strategies_hold_exclusively_and_finally_release_on_cancel(self):
        # 起始端是显式测试标注，仅验证执行接线，不冒充图像自动定位成功。
        for cls in (qte.FrostStraitQTEStrategy, qte.AbyssMawQTEStrategy):
            for cancel_while_held in (False, True):
                strategy = self.make_strategy(cls)
                regions = MechanismRegions(
                    True, GreenTarget(20, 80, (20, 30)), np.zeros(244, bool), (), ()
                )
                frame = cv2.cvtColor(
                    cv2.imread(str(FIXTURES / "green_mixed_000.png"))[96:138, 18:330],
                    cv2.COLOR_BGR2HSV,
                )
                strategy._grab_qte_frames = Mock(return_value=frame)
                strategy._find_cursor_x = Mock(side_effect=[15, 24, 45])
                clock = [0.0]
                calls = []

                def sleep():
                    clock[0] += 0.03
                    if clock[0] >= (0.06 if cancel_while_held else 0.09):
                        raise control.RunStopped("cancel")

                strategy._sleep_loop = sleep
                with (
                    patch.object(qte, "read_mechanism_regions", return_value=regions),
                    patch.object(qte.time, "monotonic", side_effect=lambda: clock[0]),
                    patch.object(inputs, "qte_key_down", side_effect=lambda: calls.append("down")),
                    patch.object(inputs, "qte_key_up", side_effect=lambda: calls.append("up")),
                ):
                    with self.assertRaises(control.RunStopped):
                        strategy.play_qte(Mock())
                self.assertEqual(calls, ["down", "up"])
                strategy._press_qte.assert_not_called()
                self.assertFalse(strategy._mechanism_policy.green.held)

    def test_release_adapter_bypasses_stopped_guard_and_has_no_driver_pause(self):
        run = control.RunControl()
        with (
            control.use_control(run),
            patch.object(inputs._input, "keyDown", return_value=True) as down,
            patch.object(inputs._input, "keyUp", return_value=True) as up,
        ):
            inputs.qte_key_down()
            down.assert_called_once_with("space", _pause=False)
            run.stopped.set()
            with self.assertRaises(control.RunStopped):
                inputs.qte_key_down()
            inputs.qte_key_up()
            up.assert_called_once_with("space", _pause=False)

    def test_missing_frame_while_held_releases_before_raising(self):
        strategy = self.make_strategy(qte.FrostStraitQTEStrategy)
        strategy._mechanism_policy.green.held = True
        with patch.object(inputs, "qte_key_up") as up:
            with self.assertRaisesRegex(RuntimeError, "画面不可用"):
                strategy._release_green_on_missing_frame()
        up.assert_called_once()
        self.assertFalse(strategy._mechanism_policy.green.held)

    def test_observer_still_closes_if_release_raises(self):
        strategy = self.make_strategy(qte.FrostStraitQTEStrategy)
        strategy._mechanism_policy.green.held = True
        session = strategy._feedback_session = Mock()
        with patch.object(inputs, "qte_key_up", side_effect=OSError("release failed")):
            with self.assertRaises(OSError):
                strategy._stop_feedback()
        session.close.assert_called_once()

    def test_failed_native_release_is_retried_during_cleanup(self):
        strategy = self.make_strategy(qte.FrostStraitQTEStrategy)
        strategy._mechanism_policy.green.held = True
        with patch.object(
            inputs, "qte_key_up", side_effect=[OSError("release failed"), None]
        ) as up:
            with self.assertRaises(OSError):
                strategy._release_green_on_missing_frame()
            self.assertFalse(strategy._mechanism_policy.green.held)
            self.assertTrue(strategy._green_release_pending)
            strategy._stop_feedback()
        self.assertEqual(up.call_count, 2)
        self.assertFalse(strategy._green_release_pending)

    def test_native_down_or_cleanup_failure_still_closes_trace_and_observer(self):
        for fail_down in (True, False):
            strategy = self.make_strategy(qte.FrostStraitQTEStrategy)
            session = strategy._feedback_session = Mock()
            regions = MechanismRegions(
                True, GreenTarget(20, 80, (20, 30)), np.zeros(244, bool), (), ()
            )
            frame = cv2.imread(str(FIXTURES / "green_mixed_000.png"))[96:138, 18:330]
            strategy._grab_qte_frames = Mock(return_value=cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
            strategy._find_cursor_x = Mock(side_effect=[15, 24])
            clock = [0.0]

            def sleep():
                clock[0] += 0.03
                if clock[0] >= 0.06:
                    raise control.RunStopped("stop while held")

            strategy._sleep_loop = sleep
            with (
                patch.object(qte, "read_mechanism_regions", return_value=regions),
                patch.object(qte.time, "monotonic", side_effect=lambda: clock[0]),
                patch.object(
                    inputs,
                    "qte_key_down",
                    side_effect=OSError("down failed") if fail_down else None,
                ),
                patch.object(
                    inputs, "qte_key_up", side_effect=None if fail_down else OSError("up failed")
                ) as up,
            ):
                with self.assertRaises(OSError if fail_down else control.RunStopped) as raised:
                    strategy.play_qte(Mock())
            if not fail_down:
                self.assertIn("up failed", raised.exception.__notes__[0])
            up.assert_called_once()
            session.close.assert_called_once()
            self.assertIsNone(strategy._qte_trace)
            self.assertEqual(strategy._green_release_pending, not fail_down)

    def test_native_release_rejection_is_visible_and_restores_failsafe(self):
        previous = inputs._input.FAILSAFE
        with patch.object(inputs._input, "keyUp", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "松键未被系统接受"):
                inputs.qte_key_up()
        self.assertEqual(inputs._input.FAILSAFE, previous)

    def test_green_release_precedes_evidence_and_observer_failure_is_nonfatal(self):
        strategy = self.make_strategy(qte.FrostStraitQTEStrategy)
        target = GreenTarget(20, 80, (20, 30))
        strategy._mechanism_policy.green.observe(target, 15, 0, present=True)
        strategy._mechanism_policy.green.observe(target, 24, 0.03, present=True)
        strategy._green_release_pending = True
        strategy._green_input_started_at = 0.031
        strategy._qte_trace = Mock()
        events = []
        strategy._cache_mechanism_frame = Mock(side_effect=lambda *a, **kw: events.append("cache"))
        session = strategy._feedback_session = Mock()
        session.begin_press.side_effect = ValueError("observer unavailable")
        regions = MechanismRegions(True, target, np.zeros(244, bool), (), ())
        with (
            patch.object(qte, "read_mechanism_regions", return_value=regions),
            patch.object(qte.time, "monotonic", return_value=0.06),
            patch.object(inputs, "qte_key_up", side_effect=lambda: events.append("up")),
            self.assertLogs(qte.log.name, level="ERROR"),
        ):
            handled, _ = strategy._mechanism_step(np.zeros((19, 244, 3), np.uint8), 45)
        self.assertTrue(handled)
        self.assertEqual(events[0], "up")
        self.assertEqual(session.begin_press.call_args.kwargs, {"pressed_at": 0.06})
        self.assertEqual(session.begin_press.call_args.args[0]["hold_started_at_monotonic"], 0.031)
        strategy._press_qte.assert_not_called()

    def test_explicit_release_time_survives_later_evidence_submission(self):
        strategy = self.make_strategy(qte.FrostStraitQTEStrategy)
        session = FeedbackSession(strategy._feedback_config, strategy.region)
        with patch("bd2_fishing.game.fishing.feedback.time.monotonic", return_value=20):
            self.assertTrue(session.begin_press({"action_kind": "green_hold"}, pressed_at=19.9))
        self.assertEqual(session.presses.get_nowait()[0], 19.9)

    def test_first_mechanism_frame_survives_reused_capture_buffer(self):
        strategy = self.make_strategy(qte.FrostStraitQTEStrategy)
        strategy.catch_observer = Mock(evidence_frames={}, evidence_metadata={})
        frame = np.full((42, 312, 3), 100, np.uint8)
        strategy._grab_qte_frames(Mock(grab=Mock(return_value=frame)))
        strategy._cache_mechanism_frame("mechanism_first_green.png", first_only=True)
        frame[:] = 200
        strategy._cache_mechanism_frame("mechanism_first_green.png", first_only=True)
        self.assertTrue(
            (strategy.catch_observer.evidence_frames["mechanism_first_green.png"] == 100).all()
        )
        metadata = strategy.catch_observer.evidence_metadata["mechanism_frames"][
            "mechanism_first_green.png"
        ]
        self.assertEqual(metadata["frame_region"], strategy.roi_pos.as_tuple())
        self.assertIsNotNone(metadata["captured_at_monotonic"])

    def test_green_raw_frames_never_fall_back_to_single_click(self):
        for cls in (qte.FrostStraitQTEStrategy, qte.AbyssMawQTEStrategy):
            strategy = self.make_strategy(cls)
            frame = cv2.imread(str(FIXTURES / "green_mixed_000.png"))[96:138, 18:330]
            strategy._grab_qte_frames = Mock(return_value=cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
            strategy._sleep_loop = Mock(side_effect=[None, None, control.RunStopped("end")])
            with patch.object(inputs, "qte_key_down") as down:
                with self.assertRaises(control.RunStopped):
                    strategy.play_qte(Mock())
            down.assert_not_called()
            strategy._press_qte.assert_not_called()

    def test_purple_overlap_blocks_current_cursor_but_keeps_safe_blue_target(self):
        strategy = self.make_strategy(qte.FrostStraitQTEStrategy)
        hsv = np.zeros((19, 244, 3), np.uint8)
        hsv[:, 40:90] = (99, 200, 255)
        hsv[:, 130:155] = (25, 200, 255)
        hsv[2:17, 127:158] = (145, 200, 240)
        strategy._split_roi_and_time = lambda frame: (frame, frame)
        strategy._grab_qte_frames = Mock(return_value=hsv)
        strategy._find_cursor_x = Mock(side_effect=[140, 60, 60])
        strategy._sleep_loop = Mock(side_effect=[None, None, control.RunStopped("end")])
        with self.assertRaises(control.RunStopped):
            strategy.play_qte(Mock())
        strategy._press_qte.assert_called_once()
        self.assertEqual(strategy._press_qte.call_args.args, ("blue_fallback",))
        self.assertEqual(strategy._press_qte.call_args.kwargs["cursor_x"], 60)
