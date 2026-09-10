"""外观实例的时序与身份约束；图示消失从不充当机制解除证据。"""

import unittest

from bd2_fishing.game.fishing.mechanics.lifecycle import AppearanceTracker


class AppearanceLifecycleTests(unittest.TestCase):
    def test_two_same_color_regions_keep_independent_ids_and_endings(self):
        tracker = AppearanceTracker()
        pair = [("red_region", (10, 20)), ("red_region", (50, 60))]
        self.assertEqual(tracker.observe(pair, 0), [])
        self.assertEqual(len(tracker.observe(pair, 0.02)), 2)
        tracker.observe(pair[1:], 0.04)
        tracker.observe(pair[1:], 0.06)
        first, second = tracker.instances
        self.assertEqual((first.state, second.state), ("disappeared", "active"))
        self.assertEqual((first.instance_id, second.instance_id), (1, 2))
        records = tracker.snapshot(
            [{"attempt": 1, "pressed_at": 0.01}, {"attempt": 2, "pressed_at": 0.05}]
        )
        self.assertEqual(records[0]["attempts_in_observed_interval"], [1])
        self.assertEqual(records[1]["attempts_in_observed_interval"], [1, 2])
        self.assertTrue(all(row["result"] == "unknown" for row in records))

    def test_reappearing_region_is_a_new_instance_after_confirmed_absence(self):
        tracker = AppearanceTracker()
        detection = [("bubble_candidate", (20, 40))]
        for stamp, frame in (
            (0, detection),
            (0.02, detection),
            (0.04, []),
            (0.06, []),
            (0.08, detection),
            (0.1, detection),
        ):
            tracker.observe(frame, stamp)
        self.assertEqual([x.state for x in tracker.instances], ["disappeared", "active"])
        self.assertEqual(tracker.instances[1].first_seen, 0.08)

    def test_gap_inactive_qte_or_geometry_change_never_claims_disappearance(self):
        for change in ("gap", "inactive", "geometry"):
            with self.subTest(change=change):
                tracker = AppearanceTracker()
                frame = [("purple_region", (10, 20))]
                tracker.observe(frame, 0, shape=(19, 244, 3))
                tracker.observe(frame, 0.02, shape=(19, 244, 3))
                tracker.observe(
                    [],
                    1 if change == "gap" else 0.04,
                    observable=change != "inactive",
                    shape=(30, 360, 3) if change == "geometry" else (19, 244, 3),
                )
                self.assertEqual(tracker.instances[0].state, "unknown")

    def test_duplicate_timestamp_and_single_frame_flicker_do_not_confirm(self):
        tracker = AppearanceTracker()
        frame = [("red_region", (10, 20))]
        tracker.observe(frame, 0)
        tracker.observe(frame, 0)
        tracker.observe([], 0.01)
        tracker.observe(frame, 0.02)
        self.assertIsNone(tracker.instances[0].confirmed_at)
        tracker.observe(frame, 0.03)
        self.assertEqual(tracker.instances[0].confirmed_at, 0.03)

    def test_merging_regions_ends_old_identity_as_unknown(self):
        tracker = AppearanceTracker()
        separate = [("red_region", (10, 20)), ("red_region", (30, 40))]
        tracker.observe(separate, 0)
        tracker.observe(separate, 0.02)
        tracker.observe([("red_region", (10, 40))], 0.04)
        self.assertEqual([x.state for x in tracker.instances], ["unknown", "unknown", "candidate"])
        self.assertEqual(tracker.instances[0].end_reason, "association_ambiguous")

    def test_snapshot_is_detached_and_instance_count_is_bounded(self):
        tracker = AppearanceTracker(limit=2)
        frame = [("red_region", (10, 20))]
        tracker.observe(frame, 0)
        tracker.observe(frame, 0.02)
        snapshot = tracker.snapshot()
        tracker.interrupt(0.03, "observer_closed")
        self.assertEqual(snapshot[0]["state"], "active")
        for i in range(1, 30):
            tracker.observe([("red_region", (i * 50, i * 50 + 10))], i * 0.1)
        self.assertEqual(len(tracker.instances), 2)
        self.assertGreater(tracker.dropped, 0)
