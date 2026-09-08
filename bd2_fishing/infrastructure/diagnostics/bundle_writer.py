"""异常与结算共用的有界证据写入器，不依赖具体游戏玩法。"""

from __future__ import annotations

import json
import logging
import queue
import threading
import traceback
from zipfile import ZIP_STORED, ZipFile

import cv2

from bd2_fishing.infrastructure.diagnostics.retention import evidence_path, prune_evidence
from bd2_fishing.runtime.context import get_logger

log = logging.getLogger(__name__)


_jobs = queue.Queue(maxsize=8)


_writer = None


_writer_lock = threading.Lock()


def submit(directory, max_events, metadata, frames, done, *, exception_info=None):
    """提交已有证据；队列和写入线程始终由本模块持有。"""
    global _writer
    with _writer_lock:
        if _writer is None or not _writer.is_alive():
            _writer = threading.Thread(target=_save_worker, name="evidence-writer", daemon=True)
            _writer.start()
    done.clear()
    try:
        _jobs.put_nowait((directory, max_events, metadata, frames, done, exception_info))
    except queue.Full:
        done.set()
        return False
    return True


def _save_worker():
    while True:
        directory, limit, metadata, frames, done, exception_info = _jobs.get()
        job_log = get_logger(__name__, metadata.get("round_id"))
        try:
            if exception_info:
                metadata = dict(
                    metadata,
                    details=dict(
                        metadata.get("details", {}),
                        traceback="".join(traceback.format_exception(*exception_info)),
                    ),
                )
            directory.mkdir(parents=True, exist_ok=True)
            path = evidence_path(directory, "event")
            temporary = path.with_suffix(".tmp")
            with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
                for name, frame in frames.items():
                    ok, data = cv2.imencode(".png", frame)
                    if not ok:
                        raise RuntimeError("维护证据编码失败")
                    archive.writestr(name, data.tobytes())
                archive.writestr(
                    "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2)
                )
            temporary.replace(path)
            prune_evidence(directory, limit)
            job_log.info("维护证据已保存: %s；证据ID=%s", path, metadata["evidence_id"])
        except Exception:
            job_log.exception("维护证据保存失败")
        finally:
            done.set()
            # 等待下一项任务前释放图片及 traceback 对业务栈的引用。
            del frames, metadata, exception_info
