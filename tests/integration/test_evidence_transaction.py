"""失败写入必须清理临时文件，并保留此前完整证据。"""

import configparser
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np

from bd2_fishing.game.fishing.feedback_rules import Outcome
from bd2_fishing.game.fishing.hook_diagnostics import HookDiagnostics
from bd2_fishing.infrastructure import settings
from bd2_fishing.infrastructure.diagnostics import bundle_writer
from bd2_fishing.infrastructure.diagnostics.qte_evidence import EvidenceWriter
from bd2_fishing.infrastructure.diagnostics.retention import evidence_archive, evidence_path
from bd2_fishing.runtime.geometry import Rect


class EvidenceTransactionTests(unittest.TestCase):
    def test_failed_encoding_and_rename_leave_no_temporary_or_partial_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = evidence_path(root, "event")
            with evidence_archive(previous, 1) as archive:
                archive.writestr("metadata.json", '{"complete": true}')
            original = previous.read_bytes()
            for mode in ("encode", "rename"):
                for _ in range(3):
                    candidate = evidence_path(root, "event")
                    with self.subTest(mode=mode), self.assertRaises(OSError):
                        with patch.object(Path, "replace", side_effect=OSError("rename failed")):
                            with evidence_archive(candidate, 1) as archive:
                                archive.writestr("partial", b"already encoded")
                                if mode == "encode":
                                    raise OSError("encoding failed")
                    self.assertEqual(list(root.iterdir()), [previous])
                    self.assertEqual(previous.read_bytes(), original)
            candidate = evidence_path(root, "event")
            with evidence_archive(candidate, 1) as archive:
                archive.writestr("metadata.json", '{"recovered": true}')
            self.assertEqual(list(root.iterdir()), [candidate])
            with ZipFile(candidate) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(json.loads(archive.read("metadata.json")), {"recovered": True})

    def test_all_three_writers_cleanup_after_replace_failure_and_can_retry(self):
        config = configparser.ConfigParser()
        config.read_string(settings.DEFAULT_CONFIG_CONTENT)
        region = Rect(0, 0, 20, 20)
        frame = np.zeros((20, 20, 3), np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qte = EvidenceWriter(root / "qte", config, region, region)
            hook = HookDiagnostics(root / "hook", interval_seconds=0)

            def save_bundle():
                done = threading.Event()
                self.assertTrue(
                    bundle_writer.submit(
                        root / "bundle", 1, {"evidence_id": "test"}, {"frame.png": frame}, done
                    )
                )
                self.assertTrue(done.wait(2))

            def save_hook():
                self.assertTrue(
                    hook.save_timeout(
                        None,
                        region,
                        region,
                        (0, 0, 0),
                        (255, 255, 255),
                        1,
                        "test",
                        context_frame=frame,
                    )
                )
                hook._worker.join(2)
                self.assertFalse(hook._worker.is_alive())

            def save_qte():
                qte.save(Outcome(1, 1, 1.1, "miss", "miss", "test"), [(1, frame)])

            try:
                with patch.object(Path, "replace", side_effect=PermissionError("rename denied")):
                    with self.assertLogs(
                        "bd2_fishing.infrastructure.diagnostics.bundle_writer", level="ERROR"
                    ):
                        save_bundle()
                    with self.assertLogs(
                        "bd2_fishing.game.fishing.hook_diagnostics", level="WARNING"
                    ):
                        save_hook()
                    with self.assertRaises(PermissionError):
                        save_qte()
                self.assertFalse([p for p in root.rglob("*") if p.is_file()])
                save_bundle()
                save_hook()
                save_qte()
                self.assertEqual(len(list(root.rglob("*.zip"))), 3)
                self.assertFalse(list(root.rglob("*.tmp")))
            finally:
                qte.close()
