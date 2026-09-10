"""正常运行的异常取证：复用已有帧，错误事件入队，后台编码和写盘。"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

from bd2_fishing.infrastructure import paths
from bd2_fishing.infrastructure.diagnostics import bundle_writer
from bd2_fishing.runtime.context import current_round_id

_active = None
log = logging.getLogger(__name__)


def observe(frame, region, source="control"):
    """只缓存已有 BGR 帧；每个来源至多每 100ms 复制一次，不增加截图调用。"""
    recorder = _active
    if recorder is not None and frame is not None:
        try:
            recorder.observe(frame, region, source)
        except Exception:
            log.warning("缓存维护截图失败；继续原识别流程", exc_info=True)


def report(event, **details):
    recorder = _active
    if recorder is not None:
        recorder.report(event, **details)


class IncidentRecorder(logging.Handler):
    def __init__(self, directory=None, *, max_events=100, context=None):
        super().__init__(logging.WARNING)
        self.directory = Path(directory or Path(paths.get_diagnostics_path()) / "incidents")
        self.max_events = max(1, max_events)
        self.context = context or {}
        self.frames = OrderedDict()
        self.frame_lock = threading.Lock()
        self.pending = []

    def observe(self, frame, region, source):
        stamp = time.monotonic()
        with self.frame_lock:
            previous = self.frames.get(source)
            if previous is not None and stamp - previous[0] < 0.1:
                return
            bounds = region.as_tuple() if hasattr(region, "as_tuple") else tuple(region)
            self.frames[source] = (stamp, bounds, frame.copy(), current_round_id())
            self.frames.move_to_end(source)
            while len(self.frames) > 4:
                self.frames.popitem(last=False)

    def report(self, event, *, exception_info=None, **details):
        try:
            now = time.monotonic()
            with self.frame_lock:
                samples = list(self.frames.items())
            frames, frame_metadata = {}, []
            for index, (source, (stamp, bounds, frame, round_id)) in enumerate(samples):
                name = f"cached_{index:02d}.png"
                frames[name] = frame
                frame_metadata.append(
                    dict(
                        file=name,
                        source=source,
                        region=bounds,
                        captured_at_monotonic=stamp,
                        age_seconds=now - stamp,
                        round_id=round_id,
                    )
                )
            metadata = dict(
                self.context,
                event=event,
                evidence_id=uuid.uuid4().hex,
                round_id=current_round_id(),
                saved_at_unix=time.time(),
                frames=frame_metadata,
                details=details,
                screenshots_available=bool(frames),
                screenshot_note="已有检测帧，时间和区域见 frames；不是异常瞬间重新截图。"
                if frames
                else "尚未取得有效游戏帧，无法提供截图；未截取其他桌面内容。",
            )
            done = threading.Event()
            if not bundle_writer.submit(
                self.directory,
                self.max_events,
                metadata,
                frames,
                done,
                exception_info=exception_info,
            ):
                log.warning(
                    "异常证据队列已满，事件仅保留日志: %s",
                    event,
                    extra={"user_message": "截图保存任务过多，此次异常仅保留日志。"},
                )
            else:
                with self.frame_lock:
                    self.pending = [item for item in self.pending if not item.is_set()]
                    self.pending.append(done)
        except Exception:
            log.warning(
                "无法提交异常证据: %s",
                event,
                exc_info=True,
                extra={"user_message": "此次异常截图无法提交保存，请保留日志供排查。"},
            )

    def emit(self, record):
        if not record.name.startswith("bd2_fishing."):
            return
        if ".infrastructure.diagnostics." in record.name:
            return
        if record.levelno < logging.ERROR and not record.exc_info:
            return
        try:
            self.report(
                "application_error",
                logger=record.name,
                message=record.getMessage(),
                exception_info=record.exc_info,
            )
        except Exception:
            log.warning("无法记录错误现场", exc_info=True)

    def drain(self, timeout=2):
        deadline = time.monotonic() + timeout
        for done in list(self.pending):
            if not done.wait(max(0, deadline - time.monotonic())):
                log.warning("异常证据仍在后台保存，立即退出进程可能丢失未完成记录")
                break


@contextmanager
def recording_session(**kwargs):
    global _active
    recorder = IncidentRecorder(**kwargs)
    previous, _active = _active, recorder
    logging.getLogger().addHandler(recorder)
    try:
        yield recorder
    finally:
        logging.getLogger().removeHandler(recorder)
        _active = previous
        recorder.drain()
        recorder.close()
