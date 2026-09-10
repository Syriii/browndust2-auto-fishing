"""在临时安装目录验证真实文件替换、损坏拒绝、回滚与数据隔离。"""

import configparser
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from bd2_fishing.app.desktop import DesktopServices
from bd2_fishing.app.startup import prepare_configuration
from bd2_fishing.app.updates import UpdateService
from bd2_fishing.infrastructure.maintenance import cleanup, prune_files
from bd2_fishing.infrastructure.updates import github, package, transaction


def make_tree(root, *, version="0.2.0", extra=None):
    root.mkdir(parents=True, exist_ok=True)
    files = {
        package.EXE: b"new executable",
        package.HELPER: b"updater",
        "_internal/python.dll": b"new runtime",
    }
    files.update(extra or {})
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    return package.create_manifest(root, version)


def make_zip(root, target):
    with ZipFile(target, "w") as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, package.APP + "/" + path.relative_to(root).as_posix())


class PortableUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.install = self.root / "install"
        self.job = self.install / "cache/updates" / ("a" * 32)
        self.stage = self.job / "stage"

    def prepared(self):
        make_tree(self.install, version="0.1.0", extra={"_internal/obsolete.dll": b"old"})
        (self.install / package.EXE).write_bytes(b"old executable")
        make_tree(self.stage)
        for name in (
            "config/config.ini",
            "data/calibration.json",
            "logs/a.log",
            "screenshots/a.zip",
            "personal.txt",
        ):
            path = self.install / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"keep unchanged")

    def test_complete_update_removes_old_dependency_preserves_userdata(self):
        self.prepared()
        transaction.apply_update(self.install, self.job)
        self.assertEqual((self.install / package.EXE).read_bytes(), b"new executable")
        self.assertFalse((self.install / "_internal/obsolete.dll").exists())
        self.assertEqual((self.install / "config/config.ini").read_bytes(), b"keep unchanged")
        self.assertEqual((self.install / "personal.txt").read_bytes(), b"keep unchanged")
        for name in ("data/calibration.json", "logs/a.log", "screenshots/a.zip"):
            self.assertEqual((self.install / name).read_bytes(), b"keep unchanged")

    def test_failure_after_some_replacements_restores_every_original(self):
        self.prepared()
        original = transaction.replace_file

        def fail_once(source, target):
            if source == self.stage / "_internal/python.dll":
                raise PermissionError("simulated locked DLL")
            return original(source, target)

        with patch.object(transaction, "replace_file", side_effect=fail_once):
            with self.assertRaises(PermissionError):
                transaction.apply_update(self.install, self.job)
        self.assertEqual((self.install / package.EXE).read_bytes(), b"old executable")
        self.assertTrue((self.install / "_internal/obsolete.dll").is_file())
        self.assertEqual(
            json.loads((self.job / "journal.json").read_text())["phase"], "rolled_back"
        )

    def test_interruption_recovery_is_repeatable(self):
        self.prepared()
        original = transaction.replace_file

        def interrupt(source, target):
            if source == self.stage / "_internal/python.dll":
                raise KeyboardInterrupt()
            return original(source, target)

        with patch.object(transaction, "replace_file", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                transaction.apply_update(self.install, self.job)
        transaction.rollback(self.install, self.job)
        transaction.rollback(self.install, self.job)
        self.assertEqual((self.install / package.EXE).read_bytes(), b"old executable")

    def test_corrupt_staged_file_leaves_old_install_untouched(self):
        self.prepared()
        (self.stage / package.EXE).write_bytes(b"corrupted")
        with self.assertRaises(ValueError):
            transaction.apply_update(self.install, self.job)
        self.assertEqual((self.install / package.EXE).read_bytes(), b"old executable")
        self.assertFalse((self.job / "journal.json").exists())

    def test_zip_full_roundtrip_and_arbitrary_filename(self):
        make_tree(self.root / "source")
        archive = self.root / "renamed.zip"
        make_zip(self.root / "source", archive)
        manifest = package.unpack_verified(archive, self.stage)
        package.verify_tree(self.stage, manifest)

    def test_zip_extra_userdata_or_traversal_rejected(self):
        make_tree(self.root / "source")
        for i, name in enumerate(("config/config.ini", "../escaped.txt", "_internal/CON.dll")):
            archive = self.root / f"bad{i}.zip"
            make_zip(self.root / "source", archive)
            with ZipFile(archive, "a") as zip_file:
                zip_file.writestr(package.APP + "/" + name, "bad")
            with self.assertRaises(ValueError):
                package.unpack_verified(archive, self.root / f"stage{i}")
        self.assertFalse((self.root / "escaped.txt").exists())

    def test_zip_hash_mismatch_and_missing_files(self):
        source = self.root / "source"
        make_tree(source)
        (source / package.EXE).write_bytes(b"BAD executable")
        archive = self.root / "bad.zip"
        make_zip(source, archive)
        with self.assertRaises(ValueError):
            package.unpack_verified(archive, self.stage)

    def test_manifest_cannot_manage_user_data(self):
        manifest = make_tree(self.root / "source")
        manifest["files"]["config/config.ini"] = dict(size=0, sha256="0" * 64)
        with self.assertRaises(ValueError):
            package.read_manifest(json.dumps(manifest).encode())

    def test_unsafe_windows_paths(self):
        for name in (
            "/foo",
            "a/../b",
            "C:/a",
            "a:stream",
            "a\\b",
            "nul.txt",
            "A./b",
            "a//b",
            "a/ ",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                package.safe_path(self.root, name)

    def test_installation_mutex_excludes_other_instances(self):
        with transaction.installation_lock(self.root):
            with self.assertRaises(RuntimeError):
                with transaction.installation_lock(self.root):
                    self.fail("second instance acquired lock")

    def test_first_configuration_and_idempotent_validation(self):
        path = self.root / "config/config.ini"
        self.assertTrue(prepare_configuration(path)["created"])
        raw = path.read_bytes()
        self.assertFalse(prepare_configuration(path)["repaired"])
        self.assertEqual(raw, path.read_bytes())

    def test_legacy_configuration_migrates_without_overwriting_existing(self):
        old = self.root / "config.ini"
        old.write_text("; personal note\n[backpack]\nauto_clear_enabled = false\n", encoding="utf8")
        path = self.root / "config/config.ini"
        prepare_configuration(path, legacy=old)
        self.assertIn("; personal note", path.read_text(encoding="utf-8-sig"))
        self.assertIn("false", path.read_text(encoding="utf-8-sig"))
        raw = path.read_bytes()
        old.write_text("broken", encoding="utf8")
        prepare_configuration(path, legacy=old)
        self.assertEqual(raw, path.read_bytes())

    def test_invalid_config_is_backed_up_and_dangerous_option_disabled(self):
        path = self.root / "config.ini"
        path.write_bytes(b"invalid ini")
        result = prepare_configuration(path)
        self.assertTrue(result["repaired"])
        self.assertEqual(next(self.root.glob("config.invalid-*.ini")).read_bytes(), b"invalid ini")
        config = configparser.ConfigParser()
        config.read(path, encoding="utf-8-sig")
        self.assertFalse(config.getboolean("backpack", "auto_clear_enabled"))

    def test_retention_preserves_keep_active_and_unrelated_files(self):
        for name in ("expired.zip", "recent.zip", "keep/important.zip", "personal.txt"):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"data")
        os.utime(self.root / "expired.zip", (0, 0))
        self.assertEqual(prune_files(self.root, days=30, max_bytes=100, suffixes=(".zip",)), 1)
        self.assertTrue((self.root / "keep/important.zip").exists())
        self.assertTrue((self.root / "personal.txt").exists())
        self.assertTrue((self.root / "recent.zip").exists())

    def test_pending_update_never_pruned(self):
        path = self.root / "cache/updates"
        path.mkdir(parents=True)
        (path / "pending.json").write_text("{}")
        (path / "backup.zip").write_bytes(b"keep")
        os.utime(path / "backup.zip", (0, 0))
        cleanup(self.root, configparser.ConfigParser())
        self.assertTrue((path / "backup.zip").exists())

    def test_official_release_asset_selection_and_version_comparison(self):
        base = github.RELEASES_URL + "/download/v0.10.0/"
        response = dict(
            tag_name="v0.10.0",
            assets=[
                dict(name=n, browser_download_url=base + n)
                for n in (github.ASSET_NAME, github.ASSET_NAME + ".sha256")
            ],
        )
        with patch.object(github, "fetch", return_value=json.dumps(response).encode()):
            self.assertEqual(github.latest_release("0.2.0")["version"], "0.10.0")
            self.assertIsNone(github.latest_release("0.10.0"))

    def test_bad_download_checksum_is_rejected(self):
        def fake_fetch(url, target=None, **kwargs):
            if target:
                target.write_bytes(b"bad package")
            return b"0" * 64

        with patch.object(github, "fetch", side_effect=fake_fetch):
            with self.assertRaises(ValueError):
                github.download_release(
                    dict(checksum="checksum", package="zip"), self.root, threading.Event()
                )

    def test_cache_cleanup_uses_transaction_age_not_original_file_age(self):
        self.job.mkdir(parents=True)
        old_file = self.job / "old-resource.dat"
        old_file.write_bytes(b"backup")
        os.utime(old_file, (0, 0))
        cleanup(self.install, configparser.ConfigParser())
        self.assertTrue(old_file.exists())
        os.utime(self.job, (0, 0))
        cleanup(self.install, configparser.ConfigParser())
        self.assertFalse(self.job.exists())

    def test_capacity_prunes_oldest_screenshot(self):
        for name in ("old.zip", "new.zip"):
            (self.root / name).write_bytes(b"123456")
        os.utime(self.root / "old.zip", (time.time() - 60, time.time() - 60))
        prune_files(self.root, days=30, max_bytes=6, suffixes=(".zip",))
        self.assertFalse((self.root / "old.zip").exists())
        self.assertTrue((self.root / "new.zip").exists())

    def test_invalid_retention_setting_repaired_with_backup(self):
        path = self.root / "config.ini"
        path.write_text("[storage]\nretention_days = -1\n", encoding="utf8")
        prepare_configuration(path)
        self.assertTrue(list(self.root.glob("config.invalid-*.ini")))
        config = configparser.ConfigParser()
        config.read(path, encoding="utf-8-sig")
        self.assertEqual(config.getint("storage", "retention_days"), 30)

    def test_local_service_stages_without_mutating_installation(self):
        make_tree(self.install, version="0.1.0")
        make_tree(self.root / "incoming")
        make_zip(self.root / "incoming", self.root / "local.zip")
        before = (self.install / "manifest.json").read_bytes()
        with (
            patch("bd2_fishing.app.updates.paths.get_base_path", return_value=str(self.install)),
            patch.object(sys, "frozen", True, create=True),
        ):
            service = UpdateService()
            result = service.prepare(package=self.root / "local.zip")
        self.assertEqual(result["version"], "0.2.0")
        self.assertEqual(before, (self.install / "manifest.json").read_bytes())
        self.assertFalse((self.install / "cache/updates/pending.json").exists())

    def test_local_service_refuses_downgrade(self):
        make_tree(self.install, version="0.2.0")
        make_tree(self.root / "incoming", version="0.1.0")
        make_zip(self.root / "incoming", self.root / "local.zip")
        with (
            patch("bd2_fishing.app.updates.paths.get_base_path", return_value=str(self.install)),
            patch.object(sys, "frozen", True, create=True),
        ):
            with self.assertRaises(ValueError):
                UpdateService().prepare(package=self.root / "local.zip")

    def test_update_cannot_overwrite_recovery_journal(self):
        self.prepared()
        (self.job / "journal.json").write_text('{"phase":"applying"}')
        with self.assertRaises(RuntimeError):
            transaction.apply_update(self.install, self.job)

    def test_preview_does_not_create_config_that_blocks_legacy_import(self):
        old = self.root / "config.ini"
        old.write_text("[backpack]\nauto_clear_enabled = false\n", encoding="utf8")
        new = self.root / "config/config.ini"
        services = DesktopServices(config_path=new, read_only=True)
        self.assertTrue(services.load_settings().has_section("hook"))
        self.assertFalse(new.exists())
        prepare_configuration(new, legacy=old)
        self.assertFalse(services.load_settings().getboolean("backpack", "auto_clear_enabled"))
