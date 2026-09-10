import unittest

from bd2_fishing.game.fishing.trigger_rules import TargetEntryTrigger


class TargetEntryTests(unittest.TestCase):
    def test_persistent_overlap_does_not_repeat_and_reentry_fires_immediately(self):
        trigger = TargetEntryTrigger()
        self.assertEqual(
            [trigger.observe(value, "yellow") for value in (True, True, True, False, True)],
            [True, False, False, False, True],
        )

    def test_unknown_frames_do_not_rearm_or_change_target(self):
        trigger = TargetEntryTrigger()
        self.assertTrue(trigger.observe(True, "yellow"))
        for _ in range(100):
            self.assertFalse(trigger.observe(None, "blue"))
        self.assertFalse(trigger.observe(True, "yellow"))

    def test_confirmed_target_mode_change_allows_new_action(self):
        trigger = TargetEntryTrigger()
        self.assertTrue(trigger.observe(True, "yellow"))
        self.assertTrue(trigger.observe(True, "blue"))
        self.assertFalse(trigger.observe(True, "blue"))
        self.assertTrue(trigger.observe(True, "yellow"))

    def test_new_round_does_not_inherit_disarmed_state(self):
        first = TargetEntryTrigger()
        self.assertTrue(first.observe(True, "yellow"))
        self.assertFalse(first.observe(True, "yellow"))
        self.assertTrue(TargetEntryTrigger().observe(True, "yellow"))
