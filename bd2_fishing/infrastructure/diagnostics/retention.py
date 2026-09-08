"""后台写入器共用的取证命名与保留规则。"""

import time
import uuid


def evidence_path(directory, prefix):
    return directory / f"{prefix}_{time.time_ns()}_{uuid.uuid4().hex[:8]}.zip"


def prune_evidence(directory, max_events, *, max_bytes=512 * 1024 * 1024):
    """只清理本类 ZIP；最新一份始终保留，失败与成功使用不同目录。"""
    files = sorted(directory.glob("*.zip"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    total = 0
    for index, path in enumerate(files):
        total += path.stat().st_size
        if index and (index >= max(1, max_events) or total > max_bytes):
            path.unlink()
