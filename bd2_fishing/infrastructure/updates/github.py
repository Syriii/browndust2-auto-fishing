"""固定官方仓库的正式 Release 查询与有界下载。"""

import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

from bd2_fishing.infrastructure.updates.package import MAX_BYTES, sha256

REPOSITORY = "Syriii/browndust2-auto-fishing"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
LATEST_URL = RELEASES_URL + "/latest"
ASSET_NAME = "BD2_AutoFishing-windows.zip"


class UpdateCheckError(RuntimeError):
    def __init__(self, message, retry_at):
        super().__init__(message)
        self.retry_at = retry_at


def retry_time(headers, now):
    """尊重服务端退避时间；无头部的限流至少冷却一小时。"""
    deadlines = []
    for key in ("Retry-After", "X-RateLimit-Reset"):
        value = headers.get(key) if headers else None
        if not value:
            continue
        try:
            if key == "X-RateLimit-Reset":
                deadline = float(value)
            else:
                deadline = now + float(value)
            if math.isfinite(deadline):
                deadlines.append(deadline)
        except ValueError:
            if key == "Retry-After":
                try:
                    deadlines.append(parsedate_to_datetime(value).timestamp())
                except (ValueError, TypeError, OverflowError):
                    pass
    return max(now + 60, *deadlines) if deadlines else now + 3600


def resolve_latest_tag():
    """官方 latest 跳转指向正式 Release，不使用匿名 REST API 配额或解析 HTML。"""
    request = urllib.request.Request(
        LATEST_URL,
        method="HEAD",
        headers={"User-Agent": "BD2-AutoFishing-Updater", "Accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            url = response.url
    except urllib.error.HTTPError as exc:
        now = time.time()
        if exc.code in (403, 429):
            raise UpdateCheckError(
                "GitHub 暂时限制访问，已暂停自动重试", retry_time(exc.headers, now)
            ) from exc
        message = "尚未找到正式 Release" if exc.code == 404 else "GitHub 更新服务暂不可用"
        raise UpdateCheckError(message, now + 300) from exc
    except (OSError, TimeoutError) as exc:
        raise UpdateCheckError("暂时无法连接 GitHub，稍后可重试", time.time() + 300) from exc
    prefix = RELEASES_URL + "/tag/"
    if not url.startswith(prefix) or not re.fullmatch(r"v?\d+\.\d+\.\d+", url[len(prefix) :]):
        raise UpdateCheckError("未能确认官方正式版本，未使用此更新地址", time.time() + 300)
    return url[len(prefix) :]


def release_from_tag(tag):
    version = tag.removeprefix("v")
    version_key(tag)
    base = RELEASES_URL + "/download/" + tag + "/"
    return dict(version=version, package=base + ASSET_NAME, checksum=base + ASSET_NAME + ".sha256")


def version_key(value):
    value = value.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("仅支持三段数字的正式版本")
    return tuple(int(part) for part in value.split("."))


def fetch(url, target=None, *, limit=2 * 1024**2, cancel=None):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "BD2-AutoFishing-Updater", "Accept": "application/octet-stream"},
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
    release = release_from_tag(resolve_latest_tag())
    if version_key(release["version"]) <= version_key(current):
        return None
    return release


def download_release(release, directory, cancel):
    checksum = fetch(release["checksum"], limit=1024, cancel=cancel).decode("ascii").split()[0]
    if not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        raise ValueError("发布包校验文件无效")
    destination = Path(directory) / "download.zip"
    fetch(release["package"], destination, limit=MAX_BYTES, cancel=cancel)
    if sha256(destination) != checksum.lower():
        raise ValueError("下载包 SHA-256 不匹配，请重新下载")
    return destination
