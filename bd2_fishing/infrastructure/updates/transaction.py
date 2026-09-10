"""备份、替换、回滚；清理仅覆盖清单管理的文件。"""

import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from bd2_fishing.infrastructure.updates.package import (
    EXE,
    HELPER,
    managed,
    read_manifest,
    safe_path,
    verify_tree,
)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def installation_lock(root, *, timeout=0):
    """主程序整个生命周期持锁；更新助手仅在所有主程序退出后获得锁。"""
    import msvcrt

    path = safe_path(root, "cache/session.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("程序或更新器仍在运行，请关闭其他窗口后重试") from None
                time.sleep(0.2)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def old_files(root):
    path = root / "manifest.json"
    if path.exists():
        return set(read_manifest(path.read_bytes())["files"])
    # 首次升级旧目录包：只接管已知 EXE、助手和原有 _internal。
    names = {name for name in (EXE, HELPER) if (root / name).is_file()}
    internal = safe_path(root, "_internal")
    if internal.exists():
        for path in internal.rglob("*"):
            relative = path.relative_to(root).as_posix()
            safe_path(root, relative)
            if path.is_file():
                names.add(relative)
    return names


def replace_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".bd2-update-tmp")
    try:
        shutil.copy2(source, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def rollback(root, job):
    """可重复恢复日志中的原文件；恢复失败保留日志和备份供下次重试。"""
    journal = json.loads((job / "journal.json").read_text(encoding="utf8"))
    if journal["phase"] in {"complete", "rolled_back", "preparing"}:
        return
    for name, existed in journal["original"].items():
        if name != "manifest.json" and not managed(name):
            raise ValueError("回滚清单包含用户数据")
        target = safe_path(root, name)
        if existed:
            replace_file(safe_path(job / "backup", name), target)
        else:
            target.unlink(missing_ok=True)
    journal["phase"] = "rolled_back"
    write_json(job / "journal.json", journal)


def apply_update(root, job):
    """调用者必须持安装锁。先完整备份，再写恢复日志，最后开始替换。"""
    root, job = Path(root).resolve(), Path(job).resolve()
    if (job / "journal.json").exists():
        raise RuntimeError("此更新事务已执行过，请先恢复并重新导入更新包")
    stage = job / "stage"
    manifest = read_manifest((stage / "manifest.json").read_bytes())
    verify_tree(stage, manifest)
    previous = old_files(root)
    incoming = set(manifest["files"])
    affected = sorted(previous | incoming | {"manifest.json"})
    original = {}
    for name in affected:
        target = safe_path(root, name)
        if target.exists() and not target.is_file():
            raise ValueError(f"程序目标不是文件：{name}")
        original[name] = target.exists()
    journal = dict(phase="preparing", original=original)
    write_json(job / "journal.json", journal)
    for name, exists in original.items():
        if exists:
            replace_file(safe_path(root, name), safe_path(job / "backup", name))
    journal["phase"] = "applying"
    write_json(job / "journal.json", journal)
    try:
        for name in sorted(incoming):
            replace_file(safe_path(stage, name), safe_path(root, name))
        for name in sorted(previous - incoming):
            safe_path(root, name).unlink(missing_ok=True)
        replace_file(stage / "manifest.json", root / "manifest.json")
        verify_tree(root, manifest)
        journal["phase"] = "complete"
        write_json(job / "journal.json", journal)
    except Exception:
        rollback(root, job)
        raise
    return manifest


def pending_job(root):
    pointer = safe_path(root, "cache/updates/pending.json")
    if not pointer.exists():
        return None
    name = json.loads(pointer.read_text(encoding="utf8"))["job"]
    if len(name) != 32 or any(c not in "0123456789abcdef" for c in name):
        raise ValueError("更新事务编号无效")
    return safe_path(root, "cache/updates/" + name)
