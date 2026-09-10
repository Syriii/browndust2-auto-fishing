"""固定官方仓库的正式 Release 查询与有界下载。"""

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from bd2_fishing.infrastructure.updates.package import MAX_BYTES, sha256

REPOSITORY = "Syriii/browndust2-auto-fishing"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSET_NAME = "BD2_AutoFishing-windows.zip"


def version_key(value):
    value = value.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("仅支持三段数字的正式版本")
    return tuple(int(part) for part in value.split("."))


def fetch(url, target=None, *, limit=2 * 1024**2, cancel=None):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "BD2-AutoFishing-Updater", "Accept": "application/vnd.github+json"},
    )
    chunks = []
    output = None
    total = 0
    deadline = time.monotonic() + 300
    try:
        if target is not None:
            output = Path(target).open("xb")
        with urllib.request.urlopen(request, timeout=15) as response:
            if urllib.parse.urlsplit(response.url).scheme != "https":
                raise ValueError("下载地址必须使用 HTTPS")
            while True:
                if (cancel and cancel.is_set()) or time.monotonic() > deadline:
                    raise RuntimeError("下载已取消或超时")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError("下载大小超限")
                if output:
                    output.write(chunk)
                else:
                    chunks.append(chunk)
        return b"".join(chunks)
    finally:
        if output:
            output.close()


def latest_release(current):
    release = json.loads(fetch(API_URL))
    version = release["tag_name"].removeprefix("v")
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("仅接受已发布的正式版本")
    if version_key(version) <= version_key(current):
        return None
    assets = {asset["name"]: asset for asset in release.get("assets", [])}
    package = assets.get(ASSET_NAME)
    checksum = assets.get(ASSET_NAME + ".sha256")
    if not package or not checksum:
        raise ValueError("此 Release 尚未提供兼容更新包及 SHA-256 校验文件")
    for asset in (package, checksum):
        url = asset["browser_download_url"]
        expected = f"https://github.com/{REPOSITORY}/releases/download/"
        if not url.startswith(expected):
            raise ValueError("更新资源不属于官方仓库")
    return dict(
        version=version,
        package=package["browser_download_url"],
        checksum=checksum["browser_download_url"],
    )


def download_release(release, directory, cancel):
    checksum = fetch(release["checksum"], limit=1024, cancel=cancel).decode("ascii").split()[0]
    if not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        raise ValueError("发布包校验文件无效")
    destination = Path(directory) / "download.zip"
    fetch(release["package"], destination, limit=MAX_BYTES, cancel=cancel)
    if sha256(destination) != checksum.lower():
        raise ValueError("下载包 SHA-256 不匹配，请重新下载")
    return destination
