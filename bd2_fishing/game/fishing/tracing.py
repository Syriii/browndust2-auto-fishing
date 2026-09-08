"""钓鱼 QTE 统计与生命周期观察，不改动按键策略。"""

import logging
import time
from collections import Counter
from functools import wraps

from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime.context import get_logger

log = get_logger(__name__)


class QTETrace:
    def __init__(self, *, detailed=False, interval=5):
        self.detailed = detailed
        self.interval = interval
        self.started = self.last_report = time.monotonic()
        self.reason = "longest_keep_time"
        self.total = Counter()
        self.counts = Counter()
        self.first = self.last = None
        self.previous_blocker = None
        self.x_min = self.x_max = None

    def observe(self, state, *, blocker=None, cursor=None, yellow=None, active=None, pressed=False):
        self.total[state] += 1
        self.counts[state] += 1
        sample = dict(
            state=state,
            blocker=blocker,
            cursor=cursor,
            yellow=yellow,
            active=active,
            pressed=pressed,
        )
        if self.first is None:
            self.first = sample
        self.last = sample
        if state == "tracking":
            if blocker != self.previous_blocker:
                log.debug(
                    "QTE 挡板变化: 原位置=%s 新位置=%s 光标=%s 有效范围=%s",
                    self.previous_blocker,
                    blocker,
                    cursor,
                    active,
                )
            self.counts["blocker_detected"] += blocker is not None
            self.counts["blocker_changes"] += blocker != self.previous_blocker
            self.counts["presses"] += bool(pressed)
            self.previous_blocker = blocker
            if blocker is not None:
                self.x_min = blocker[0] if self.x_min is None else min(self.x_min, blocker[0])
                self.x_max = blocker[0] if self.x_max is None else max(self.x_max, blocker[0])
        if self.detailed:
            log.debug("QTE 逐帧: %s", sample)
        if time.monotonic() - self.last_report >= self.interval:
            self.report()

    def report(self):
        if not self.counts:
            return
        now = time.monotonic()
        log.debug(
            "QTE 控制采样: 窗口秒=%.2f 计数=%s 挡板x范围=%s 首帧=%s 末帧=%s",
            now - self.last_report,
            dict(self.counts),
            (self.x_min, self.x_max),
            self.first,
            self.last,
        )
        self.counts.clear()
        self.first = self.last = None
        self.x_min = self.x_max = None
        self.last_report = now

    def close(self):
        self.report()
        level = logging.WARNING if self.reason == "longest_keep_time" else logging.DEBUG
        if self.reason.startswith("exception:"):
            level = logging.ERROR
        log.log(
            level,
            "QTE 退出: 原因=%s 耗时秒=%.2f 总采样=%s（不代表捕获成功）",
            self.reason,
            time.monotonic() - self.started,
            dict(self.total),
        )


def trace_qte(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        run_control.set_status("QTE 进行中")
        trace = QTETrace(detailed=self.qte_detail_log)
        self._qte_trace = trace
        log.info("QTE 开始")
        log.debug(
            "QTE 参数: 策略=%s ROI=%s 最长秒=%s 逐帧文件日志=%s",
            type(self).__name__,
            self.roi_pos.as_tuple(),
            self.longest_keep_time,
            self.qte_detail_log,
        )
        try:
            start_feedback = getattr(self, "_start_feedback", None)
            if start_feedback is not None:
                start_feedback()
            return method(self, *args, **kwargs)
        except run_control.RunStopped:
            trace.reason = "cancelled"
            raise
        except BaseException as exc:
            trace.reason = f"exception:{type(exc).__name__}"
            raise
        finally:
            stop_feedback = getattr(self, "_stop_feedback", None)
            if stop_feedback is not None:
                stop_feedback()
            trace.close()
            self._qte_trace = None

    return wrapped
