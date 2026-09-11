"""已返回待机的整屏图不能替代 QTE 未命中前后帧。"""

from unittest import TestCase

from bd2_fishing.game.fishing.evidence_selection import select_round_frames


class EvidenceSelectionTests(TestCase):
    def test_ordinary_unknown_keeps_qte_not_ready_screen(self):
        frames = {
            name: object()
            for name in (
                "settlement.png",
                "resume_latest.png",
                "last_observed_qte.png",
                "mechanism_first_green.png",
            )
        }
        metadata = dict(
            result={"status": "unknown"}, page_state="idle", resume_check={"state": "idle"}
        )
        self.assertEqual(
            set(select_round_frames(frames, metadata)),
            {"last_observed_qte.png", "mechanism_first_green.png"},
        )
        self.assertEqual(len(frames), 4)

    def test_error_recovery_and_reward_evidence_are_retained(self):
        frames = {
            name: object() for name in ("settlement.png", "resume_latest.png", "reentry_error.png")
        }
        for metadata in (
            dict(result={"status": "unknown"}, page_state="panel", resume_check={"state": "idle"}),
            dict(
                result={"status": "unknown"},
                page_state="idle",
                resume_check={"state": "idle"},
                round_recovery={"status": "resumed"},
            ),
            dict(result={"status": "caught"}, page_state="idle", resume_check={"state": "idle"}),
            dict(result={"status": "unknown"}, page_state="unrecognized"),
        ):
            with self.subTest(metadata=metadata):
                self.assertEqual(select_round_frames(frames, metadata), frames)
