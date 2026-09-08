"""infrastructure.diagnostics.catch_evidence：从现有实现分离的职责模块。"""

from __future__ import annotations

import itertools
import json
import logging
import queue
import threading
from zipfile import ZIP_STORED, ZipFile

import cv2

from bd2_fishing.runtime.context import get_logger

log = logging.getLogger(__name__)


_jobs = queue.Queue(maxsize=2)


_writer = None


_writer_lock = threading.Lock()


def submit(directory, max_events, metadata, frames, done):
    """提交已有证据；队列和写入线程始终由本模块持有。"""
    global _writer
    with _writer_lock:
        if _writer is None or not _writer.is_alive():
            _writer = threading.Thread(target=_save_worker, name="catch-evidence", daemon=True)
            _writer.start()
    done.clear()
    try:
        _jobs.put_nowait((directory, max_events, metadata, frames, done))
    except queue.Full:
        done.set()
        return False
    return True


_slots = itertools.count()


def _save_worker():
    while True:
        directory, limit, metadata, frames, done = _jobs.get()
        job_log = get_logger(__name__, metadata.get("round_id"))
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"catch_{next(_slots) % limit + 1:02d}.zip"
            temporary = path.with_suffix(".tmp")
            with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
                for name, frame in frames.items():
                    ok, data = cv2.imencode(".png", frame)
                    if not ok:
                        raise RuntimeError("结算证据编码失败")
                    archive.writestr(name, data.tobytes())
                archive.writestr(
                    "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2)
                )
            temporary.replace(path)
            job_log.info("本轮诊断已保存: %s；证据ID=%s", path, metadata["evidence_id"])
        except Exception:
            job_log.exception("结算证据保存失败")
        finally:
            done.set()
