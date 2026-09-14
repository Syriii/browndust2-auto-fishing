"""官方跳转、跨重启缓存、限流退避与维护隔离；不使用真实网络。"""

import json
import tempfile
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from bd2_fishing.infrastructure.updates import github
from bd2_fishing.infrastructure.updates.check import ReleaseChecker
from bd2_fishing.ui.updates import UpdatePanel


class OfficialReleaseTests(TestCase):
    def resolve(self, url):
        response = Mock(url=url)
        opened = Mock()
        opened.__enter__ = Mock(return_value=response)
        opened.__exit__ = Mock(return_value=False)
        with patch.object(github.urllib.request, "urlopen", return_value=opened) as call:
            result = github.resolve_latest_tag()
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, github.LATEST_URL)
        self.assertEqual(request.get_method(), "HEAD")
        return result

    def test_official_redirect_builds_version_pinned_assets_without_api(self):
        tag = self.resolve(github.RELEASES_URL + "/tag/v0.10.0")
        release = github.release_from_tag(tag)
        self.assertEqual(release["version"], "0.10.0")
        self.assertEqual(
            release["package"], github.RELEASES_URL + "/download/v0.10.0/" + github.ASSET_NAME
        )

    def test_foreign_redirect_login_and_prerelease_tags_are_rejected(self):
        for url in (
            "https://example.com/releases/tag/v1.0.0",
            "http://github.com/" + github.REPOSITORY + "/releases/tag/v1.0.0",
            "https://github.com/login",
            github.RELEASES_URL + "/tag/v1.0.0-beta",
            github.RELEASES_URL + "/tag/v1.0.0?next=elsewhere",
        ):
            with self.subTest(url=url), self.assertRaises(github.UpdateCheckError):
                self.resolve(url)

    def test_rate_limit_headers_are_honored_without_immediate_retry(self):
        for code in (403, 429):
            error = urllib.error.HTTPError(
                github.LATEST_URL, code, "limited", {"Retry-After": "120"}, None
            )
            with (
                patch.object(github.urllib.request, "urlopen", side_effect=error) as call,
                patch.object(github.time, "time", return_value=1000),
            ):
                with self.assertRaises(github.UpdateCheckError) as raised:
                    github.resolve_latest_tag()
            self.assertEqual(raised.exception.retry_at, 1120)
            call.assert_called_once()

    def test_rate_limit_defaults_and_reset_date(self):
        self.assertEqual(github.retry_time({}, 1000), 4600)
        self.assertEqual(
            github.retry_time({"X-RateLimit-Reset": "5000", "Retry-After": "10"}, 1000), 5000
        )
        self.assertEqual(
            github.retry_time({"Retry-After": "Thu, 01 Jan 1970 00:30:00 GMT"}, 1000), 1800
        )
        self.assertEqual(github.retry_time({"Retry-After": "invalid"}, 1000), 4600)

    def test_missing_release_and_network_errors_are_not_latest_success(self):
        for error in (
            urllib.error.URLError("offline"),
            urllib.error.HTTPError(github.LATEST_URL, 404, "missing", {}, None),
        ):
            with patch.object(github.urllib.request, "urlopen", side_effect=error):
                with self.assertRaises(github.UpdateCheckError):
                    github.latest_release("0.3.5")


class ReleaseCacheTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "release-check.json"
        self.clock = 10000
        timer = patch(
            "bd2_fishing.infrastructure.updates.check.time.time", side_effect=lambda: self.clock
        )
        timer.start()
        self.addCleanup(timer.stop)
        query = patch.object(github, "resolve_latest_tag", return_value="v0.3.1")
        self.query = query.start()
        self.addCleanup(query.stop)

    def test_success_cache_survives_restart_and_recompares_current_version(self):
        self.assertIsNone(ReleaseChecker(self.path).check("0.3.5"))
        self.assertEqual(ReleaseChecker(self.path).check("0.3.0")["version"], "0.3.1")
        self.query.assert_called_once()
        self.clock += 3601
        ReleaseChecker(self.path).check("0.3.5")
        self.assertEqual(self.query.call_count, 2)

    def test_manual_refresh_respects_short_success_cache(self):
        checker = ReleaseChecker(self.path)
        checker.check("0.3.5")
        checker.check("0.3.5", force=True)
        self.query.assert_called_once()
        self.clock += 61
        checker.check("0.3.5", force=True)
        self.assertEqual(self.query.call_count, 2)

    def test_failure_cooldown_survives_restart_and_manual_clicks(self):
        self.query.side_effect = github.UpdateCheckError("limited", self.clock + 3600)
        with self.assertRaises(github.UpdateCheckError):
            ReleaseChecker(self.path).check("0.3.5")
        for force in (False, True):
            with self.assertRaises(github.UpdateCheckError) as raised:
                ReleaseChecker(self.path).check("0.3.5", force=force)
            self.assertTrue(raised.exception.cached)
        self.query.assert_called_once()
        self.clock += 3601
        self.query.side_effect = None
        self.assertIsNone(ReleaseChecker(self.path).check("0.3.5"))
        self.assertEqual(self.query.call_count, 2)

    def test_bad_cache_is_ignored_and_cannot_inject_download_host(self):
        for content in (
            "broken",
            "[]",
            json.dumps(
                dict(
                    schema=1,
                    checked_at=self.clock,
                    tag="../../other",
                    package="https://example.com/a",
                )
            ),
        ):
            self.path.write_text(content)
            self.assertIsNone(ReleaseChecker(self.path).check("0.3.5"))
        self.assertEqual(self.query.call_count, 3)

    def test_readonly_cache_keeps_in_memory_cooldown(self):
        checker = ReleaseChecker(self.path)
        self.query.side_effect = github.UpdateCheckError("limited", self.clock + 3600)
        with patch(
            "bd2_fishing.infrastructure.updates.check.write_json", side_effect=OSError("readonly")
        ):
            for _ in range(2):
                with self.assertRaises(github.UpdateCheckError):
                    checker.check("0.3.5")
        self.query.assert_called_once()


class MaintenanceIsolationTests(TestCase):
    def test_update_failure_does_not_mark_storage_failed(self):
        panel = object.__new__(UpdatePanel)
        panel.app = SimpleNamespace(services=Mock())
        panel.app.services.maintain_storage.return_value = 3
        panel.service = Mock()
        panel.service.check.side_effect = RuntimeError("limited")
        result = panel._maintain(True)
        self.assertIsNone(result["storage_error"])
        self.assertIsInstance(result["update_error"], RuntimeError)

    def test_storage_failure_does_not_prevent_update_check(self):
        panel = object.__new__(UpdatePanel)
        panel.app = SimpleNamespace(services=Mock())
        panel.app.services.maintain_storage.side_effect = OSError("disk")
        panel.service = Mock()
        panel.service.check.return_value = {"version": "0.4.0"}
        result = panel._maintain(True)
        self.assertEqual(result["release"]["version"], "0.4.0")
        self.assertIsNone(result["update_error"])
        self.assertIsInstance(result["storage_error"], OSError)
