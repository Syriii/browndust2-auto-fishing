"""后台写入器共用的取证命名与保留规则。"""

import time
import uuid
from contextlib import contextmanager
from zipfile import ZIP_STORED, ZipFile


@contextmanager
def evidence_archive(path, max_events):
    """后台共用的写入事务；编码或替换失败也清理本次临时文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".zip.tmp")
    try:
        with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
            yield archive
        temporary.replace(path)
        prune_evidence(path.parent, max_events)
    finally:
        temporary.unlink(missing_ok=True)


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
