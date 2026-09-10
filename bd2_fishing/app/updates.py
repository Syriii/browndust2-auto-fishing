"""桌面更新用例：下载或选择 ZIP，复用校验及退出后的更新流程。"""

import json
import shutil
import subprocess
import sys
import uuid
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from bd2_fishing.infrastructure import paths
from bd2_fishing.infrastructure.updates import github
from bd2_fishing.infrastructure.updates.package import HELPER, read_manifest, unpack_verified
from bd2_fishing.infrastructure.updates.transaction import pending_job, safe_path, write_json

RELEASES_URL = github.RELEASES_URL


class UpdateService:
    def __init__(self):
        self.root = Path(paths.get_base_path())
        self.supported = bool(getattr(sys, "frozen", False))
        manifest = self.root / "manifest.json"
        self.version = (
            read_manifest(manifest.read_bytes())["version"] if manifest.is_file() else "0.1.0"
        )
        if not self.supported:
            try:
                self.version = version("bd2-fishing")
            except PackageNotFoundError:
                self.version = "0.0.0"

    def check(self):
        return github.latest_release(self.version)

    def prepare(self, *, package=None, release=None, cancel=None):
        if not self.supported:
            raise RuntimeError("源码模式仅检查更新；请在发布版使用本地更新功能")
        if pending_job(self.root) is not None:
            raise RuntimeError("存在未完成更新，请重启程序先恢复")
        job = safe_path(self.root, "cache/updates/" + uuid.uuid4().hex)
        job.mkdir(parents=True)
        if release:
            package = github.download_release(release, job, cancel)
        manifest = unpack_verified(package, job / "stage")
        if github.version_key(manifest["version"]) < github.version_key(self.version):
            raise ValueError("不支持降级更新，以免新配置与旧程序不兼容")
        if release and manifest["version"] != release["version"]:
            raise ValueError("发布版本与包内清单不一致")
        if cancel and cancel.is_set():
            raise RuntimeError("更新准备已取消")
        # 助手为独立 onefile，不依赖即将被替换的 _internal。
        helper = safe_path(self.root, HELPER)
        if not helper.is_file():
            raise RuntimeError("缺少更新助手，请下载完整 ZIP 解压到新目录")
        shutil.copy2(helper, job / HELPER)
        return dict(job=job, version=manifest["version"])

    def launch(self, prepared):
        job = prepared["job"]
        write_json(self.root / "cache/updates/pending.json", dict(job=job.name))
        try:
            subprocess.Popen(
                [str(job / HELPER), "--root", str(self.root)],
                cwd=self.root,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            (self.root / "cache/updates/pending.json").unlink(missing_ok=True)
            raise

    def last_result(self):
        path = self.root / "cache/updates/result.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf8"))["message"]
        return "支持在线更新或选择从官方 Release 下载的完整 ZIP。"
