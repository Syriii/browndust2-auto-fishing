"""组合规则的纯序列测试；输入标注不是图像识别或游戏解除证据。"""

import unittest

import numpy as np

from bd2_fishing.game.fishing.mechanics.blue_target import BlueTarget
from bd2_fishing.game.fishing.mechanics.policy import MechanismPolicy, TargetPolicy
from bd2_fishing.game.fishing.mechanics.regions import GreenTarget, MechanismRegions


def regions(*, green=None, bubble=(), blocked=False):
    mask = np.zeros(120, bool)
    if blocked:
        mask[25:70] = True
    return MechanismRegions(green is not None, green, mask, (), (), bubble)


class MechanismPolicyTests(unittest.TestCase):
    def test_green_and_bubble_overlap_yields_only_hold_then_release(self):
        machine = MechanismPolicy()
        frame = regions(green=GreenTarget(20, 90, (20, 35)), bubble=((20, 50),))
        actions = [
            machine.observe(frame, x, stamp).action
            for x, stamp in ((15, 0), (30, 0.02), (45, 0.04))
        ]
        self.assertEqual(actions, ["wait", "down", "up"])
        self.assertFalse(machine.bubble.consumed)
        self.assertFalse(machine.green.held)
        # 绿条退出需要新帧确认，泡泡不能继承绿色期间的确认次数。
        ball = regions(bubble=((20, 50),))
        self.assertEqual(machine.observe(ball, 35, 0.06).action, "wait")
        self.assertEqual(machine.observe(ball, 35, 0.08).action, "normal")
        self.assertEqual(machine.observe(ball, 35, 0.10).action, "press")
        self.assertEqual(machine.observe(ball, 35, 0.12).action, "normal")

    def test_obstruction_during_hold_releases_instead_of_pressing_bubble(self):
        machine = MechanismPolicy()
        target = GreenTarget(20, 90, (20, 35))
        machine.observe(regions(green=target), 15, 0)
        self.assertEqual(machine.observe(regions(green=target), 30, 0.02).action, "down")
        decision = machine.observe(
            regions(green=target, bubble=((20, 50),), blocked=True), 30, 0.04
        )
        self.assertEqual((decision.action, decision.reason), ("up", "green_tracking_lost"))
        self.assertFalse(machine.bubble.consumed)

    def test_missing_frame_invalidates_bubble_and_requires_release_when_held(self):
        machine = MechanismPolicy()
        ball = regions(bubble=((20, 50),))
        machine.observe(ball, 35, 0)
        self.assertEqual(machine.invalidate_observation().action, "wait")
        self.assertEqual(machine.observe(ball, 35, 0.02).action, "normal")
        self.assertEqual(machine.observe(ball, 35, 0.04).action, "press")
        machine.green.held = True
        self.assertEqual(machine.invalidate_observation().action, "up")
        self.assertFalse(machine.green.held)
        self.assertTrue(machine.bubble.consumed)  # 断档不授予第二次击球。

    def test_unmarked_green_entry_blocks_every_click(self):
        machine = MechanismPolicy()
        frame = regions(green=GreenTarget(20, 90), bubble=((20, 50),))
        for i in range(8):
            decision = machine.observe(frame, 35, i * 0.02)
            self.assertEqual(
                (decision.action, decision.reason), ("wait", "green_entry_unconfirmed")
            )
        self.assertFalse(machine.bubble.consumed)


class TargetPolicyTests(unittest.TestCase):
    def test_yellow_priority_then_blue_confirmation_and_same_entry_dedup(self):
        machine = TargetPolicy()
        blue = BlueTarget(((20, 80),), ((22, 78),), True)
        self.assertEqual(
            machine.observe(yellow_present=True, yellow_overlap=True, blue=blue), "yellow"
        )
        self.assertIsNone(machine.observe(yellow_present=True, yellow_overlap=False, blue=blue))
        self.assertIsNone(machine.observe(yellow_present=False, blue=blue))
        self.assertEqual(machine.observe(yellow_present=False, blue=blue), "blue")
        for _ in range(5):
            self.assertIsNone(machine.observe(yellow_present=False, blue=blue))

    def test_unknown_or_blocked_frame_never_rearms_but_actual_exit_does(self):
        machine = TargetPolicy()
        inside = BlueTarget(((20, 80),), ((22, 78),), True)
        outside = BlueTarget(((20, 80),), ((22, 78),), False)
        machine.observe(yellow_present=False, blue=inside)
        self.assertEqual(machine.observe(yellow_present=False, blue=inside), "blue")
        for transition in ("missing", "blocked", "unknown"):
            if transition == "missing":
                machine.invalidate()
            else:
                machine.observe(yellow_present=False, blue=None, blocked=transition == "blocked")
            self.assertIsNone(machine.observe(yellow_present=False, blue=inside))
            self.assertIsNone(machine.observe(yellow_present=False, blue=inside))
        self.assertIsNone(machine.observe(yellow_present=False, blue=outside))
        self.assertEqual(machine.observe(yellow_present=False, blue=inside), "blue")
