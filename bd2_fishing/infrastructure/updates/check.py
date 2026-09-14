"""更新查询的持久缓存与失败退避；缓存只保存官方标签，不保存下载地址。"""

import json
import logging
import math
import time
from pathlib import Path

from bd2_fishing.infrastructure.updates import github
from bd2_fishing.infrastructure.updates.transaction import write_json

log = logging.getLogger(__name__)


class ReleaseChecker:
    def __init__(self, path):
        self.path = Path(path)
        self.notice = ""
        self.memory = None

    def _read(self):
        if self.memory is not None:
            return self.memory
        try:
            if self.path.stat().st_size > 8192:
                return {}
            data = json.loads(self.path.read_text(encoding="utf8"))
            return data if isinstance(data, dict) and data.get("schema") == 1 else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data):
        self.memory = dict(schema=1, **data)
        try:
            write_json(self.path, self.memory)
        except OSError:
            # 缓存不可写不能把成功查询变成更新失败；本进程仍保留退避。
            log.debug("更新查询缓存无法保存", exc_info=True)

    def check(self, current, *, force=False):
        now = time.time()
        data = self._read()
        checked = data.get("checked_at")
        valid_time = isinstance(checked, (int, float)) and 0 <= now - checked < 86400 * 7
        retry_at = data.get("retry_at")
        if (
            valid_time
            and isinstance(retry_at, (int, float))
            and math.isfinite(retry_at)
            and now < retry_at
        ):
            error = github.UpdateCheckError("更新检查仍在冷却中，未重复请求 GitHub", retry_at)
            error.cached = True
            raise error
        if valid_time and now - checked < (60 if force else 3600):
            try:
                release = github.release_from_tag(data["tag"])
            except (KeyError, ValueError, TypeError, AttributeError):
                pass
            else:
                return self._result(release, current, cached=True)
        try:
            tag = github.resolve_latest_tag()
        except github.UpdateCheckError as exc:
            self._save(dict(checked_at=now, retry_at=exc.retry_at))
            raise
        release = github.release_from_tag(tag)
        self._save(dict(checked_at=now, tag=tag))
        return self._result(release, current, cached=False)

    def _result(self, release, current, *, cached):
        self.notice = "未发现比当前版本更新的正式版本。"
        if cached:
            self.notice += "（使用近期检查缓存）"
        if github.version_key(release["version"]) > github.version_key(current):
            return release
        return None
