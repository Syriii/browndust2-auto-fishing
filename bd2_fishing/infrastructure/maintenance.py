"""仅在桌面待机维护窗口清理历史产物；不被 QTE 热循环调用。"""

import os
import time
from pathlib import Path

from bd2_fishing.infrastructure.updates.package import safe_path


def prune_files(root, *, days, max_bytes, suffixes, protect=()):
    """按时间与容量删除历史文件，跳过链接、活动文件和用户标记保留目录。"""
    root = Path(root)
    if root.is_symlink() or root.is_junction():
        return 0
    root = root.resolve()
    if not root.is_dir():
        return 0
    files = []
    for directory, subdirs, names in os.walk(root, followlinks=False):
        parent = Path(directory)
        subdirs[:] = [
            name
            for name in subdirs
            if name != "keep"
            and not (parent / name).is_symlink()
            and not (parent / name).is_junction()
        ]
        for name in names:
            path = parent / name
            if name in protect or path.is_symlink() or not any(name.endswith(s) for s in suffixes):
                continue
            try:
                stat = path.stat()
                files.append((stat.st_mtime, stat.st_size, path))
            except OSError:
                continue
    files.sort(reverse=True)
    total = sum(size for _, size, _ in files)
    cutoff = time.time() - days * 86400
    removed = 0
    for modified, size, path in reversed(files):
        if modified >= cutoff and total <= max_bytes:
            continue
        try:
            if not path.resolve().is_relative_to(root):
                continue
            path.unlink()
            total -= size
            removed += 1
        except OSError:
            continue
    return removed


def cleanup(root, config):
    root = Path(root)
    days = config.getint("storage", "retention_days", fallback=30)
    screenshot_mb = config.getint("storage", "screenshots_max_mb", fallback=2048)
    log_mb = config.getint("storage", "logs_max_mb", fallback=100)
    if not 1 <= days <= 3650 or not 10 <= min(screenshot_mb, log_mb) <= 102400:
        raise ValueError("日志与截图保留设置超出允许范围")
    if max(screenshot_mb, log_mb) > 102400:
        raise ValueError("容量上限不能超过 102400 MiB")
    count = prune_files(
        root / "logs",
        days=days,
        max_bytes=log_mb * 1024**2,
        suffixes=(".log", ".log.1", ".log.2", ".log.3"),
        protect=("auto_fishing.log", "auto_fishing.fault.log"),
    )
    count += prune_files(
        root / "screenshots",
        days=days,
        max_bytes=screenshot_mb * 1024**2,
        suffixes=(".zip", ".png", ".json"),
    )
    # 未完成事务不清理，防止中断后丢失恢复备份；完成事务七天后清理文件。
    updates = safe_path(root, "cache/updates")
    if not (updates / "pending.json").exists():
        count += prune_update_jobs(updates)
    return count


def prune_update_jobs(updates):
    """整份事务清理，不能按旧依赖的原始 mtime 提前删除新备份。"""
    if not updates.exists():
        return 0
    jobs = []
    for job in updates.iterdir():
        if len(job.name) != 32 or any(c not in "0123456789abcdef" for c in job.name):
            continue
        safe_path(updates, job.name)
        files = [safe_path(job, p.relative_to(job).as_posix()) for p in job.rglob("*")]
        total = sum(p.stat().st_size for p in files if p.is_file())
        jobs.append((job.stat().st_mtime, job, files, total))
    jobs.sort(key=lambda item: item[0])
    total = sum(item[3] for item in jobs)
    removed = 0
    for modified, job, files, size in jobs:
        if modified >= time.time() - 7 * 86400 and total <= 4 * 1024**3:
            continue
        for path in sorted(files, key=lambda p: len(p.parts), reverse=True):
            if path.is_file():
                path.unlink()
                removed += 1
            else:
                path.rmdir()
        job.rmdir()
        total -= size
    return removed
