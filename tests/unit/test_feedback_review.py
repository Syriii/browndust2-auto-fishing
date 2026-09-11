"""诊断索引只读、分类兼容、重复与坏包隔离。"""

import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts.checks.review_feedback import markdown, review


class FeedbackReviewTests(unittest.TestCase):
    def test_fail_categories_remain_distinct_from_confirmed_miss(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for category in ("unattributed_fail", "fail_without_input_result"):
                self.bundle(
                    root,
                    category + ".zip",
                    dict(
                        outcome=dict(
                            result="unknown",
                            feedback="fail",
                            diagnostics=dict(category=category),
                        )
                    ),
                )
            report = review([root])
            self.assertEqual(report["results"], {"unknown": 2})
            self.assertTrue(all("FAIL" in row["category_label"] for row in report["records"]))

    def bundle(self, root, name, metadata):
        path = root / name
        with ZipFile(path, "w") as archive:
            archive.writestr("metadata.json", json.dumps(metadata))
        return path

    def test_legacy_unknown_keeps_result_and_does_not_infer_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = dict(
                outcome=dict(result="unknown", reason="反馈等待超时", attempt=2),
                frames=[dict(file="frame_00.png")],
            )
            path = self.bundle(root, "old.zip", metadata)
            original = path.read_bytes()
            report = review([root])
            row = report["records"][0]
            self.assertEqual(row["outcome"], metadata["outcome"])
            self.assertEqual(row["category"], "legacy_unclassified")
            self.assertFalse(row["has_sampling_diagnostics"])
            self.assertEqual(row["missing_frame_files"], ["frame_00.png"])
            self.assertEqual(path.read_bytes(), original)

    def test_identical_copies_and_round_context_do_not_inflate_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.bundle(
                root, "one.zip", dict(round_id="r1", outcome=dict(result="miss", attempt=None))
            )
            (root / "copy.zip").write_bytes(path.read_bytes())
            self.bundle(root, "catch.zip", dict(round_id="r1", result=dict(status="caught")))
            report = review([root, root])
            self.assertEqual(report["unique_feedback_packages"], 1)
            self.assertEqual(len(report["exact_copies"]), 1)
            self.assertEqual(report["context_packages"], 1)
            self.assertEqual(report["unassigned_feedback"], 1)
            self.assertEqual(len(report["records"][0]["round_context"]), 1)

    def test_corrupt_and_wrong_schema_bundles_do_not_hide_valid_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broken.zip").write_bytes(b"broken")
            self.bundle(root, "wrong.zip", dict(outcome=[]))
            self.bundle(
                root,
                "good.zip",
                dict(outcome=dict(result="unknown", diagnostics=dict(category="observation_gap"))),
            )
            report = review([root])
            self.assertEqual(len(report["errors"]), 2)
            self.assertEqual(report["unknown_categories"], {"observation_gap": 1})
            self.assertIn("核对实际采样间隔", markdown(report))

    def test_unrecognized_category_is_preserved_and_missing_round_is_not_linked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.bundle(
                root,
                "future.zip",
                dict(outcome=dict(result="unknown", diagnostics=dict(category="future_reason"))),
            )
            self.bundle(root, "context.zip", dict(event="scene"))
            row = review([root])["records"][0]
            self.assertEqual(row["category"], "future_reason")
            self.assertEqual(row["round_context"], [])
            self.assertEqual(row["category_label"], "未识别的诊断分类")

    def test_nonexistent_input_is_not_reported_as_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "不存在"):
                review([Path(directory) / "missing"])
