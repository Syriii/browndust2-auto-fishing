"""保留 OCR 原始警告与 QTE 统计，不在正常控制台逐帧刷屏。"""

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import logging
import time

import run_control


_ocr_context = ContextVar("ocr_log_context", default="未指定场景")
from logging_context import get_logger, current_round_id
log = get_logger(__name__)


@contextmanager
def ocr_log_context(purpose, region, expected_empty=False):
    context = f"场景={purpose} ROI={region.as_tuple()} 允许无文字={expected_empty}"
    token = _ocr_context.set(context)
    try:
        yield context
    finally:
        _ocr_context.reset(token)


class OCRContextFilter(logging.Filter):
    def filter(self, record):
        # 不删除记录、不更改等级；原始消息和第三方代码位置均保留。
        record.msg = f"[OCR {_ocr_context.get()} {record.filename}:{record.lineno}] {record.getMessage()}"
        if current_round_id():
            record.round_id = current_round_id()
            record.msg = f"[轮次={record.round_id}] {record.msg}"
        record.args = ()
        return True


def route_rapidocr_logs():
    """在 RapidOCR 导入后调用；统一交给项目的控制台和滚动文件处理器。"""
    logger = logging.getLogger("RapidOCR")
    logger.handlers.clear()
    logger.propagate = True
    if not any(isinstance(item, OCRContextFilter) for item in logger.filters):
        logger.addFilter(OCRContextFilter())


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
        sample = dict(state=state, blocker=blocker, cursor=cursor, yellow=yellow,
                      active=active, pressed=pressed)
        if self.first is None:
            self.first = sample
        self.last = sample
        if state == "tracking":
            if blocker != self.previous_blocker:
                log.debug("QTE 挡板变化: 原位置=%s 新位置=%s 光标=%s 有效范围=%s",
                          self.previous_blocker, blocker, cursor, active)
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
        log.debug("QTE 控制采样: 窗口秒=%.2f 计数=%s 挡板x范围=%s 首帧=%s 末帧=%s",
                 now - self.last_report, dict(self.counts), (self.x_min, self.x_max), self.first, self.last)
        self.counts.clear()
        self.first = self.last = None
        self.x_min = self.x_max = None
        self.last_report = now

    def close(self):
        self.report()
        level = logging.WARNING if self.reason == "longest_keep_time" else logging.DEBUG
        if self.reason.startswith("exception:"):
            level = logging.ERROR
        log.log(level, "QTE 退出: 原因=%s 耗时秒=%.2f 总采样=%s（不代表捕获成功）",
                self.reason, time.monotonic() - self.started, dict(self.total))


def trace_qte(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        run_control.set_status("QTE 进行中")
        trace = QTETrace(detailed=self.qte_detail_log)
        self._qte_trace = trace
        log.info("QTE 开始")
        log.debug("QTE 参数: 策略=%s ROI=%s 最长秒=%s 逐帧文件日志=%s",
                 type(self).__name__, self.roi_pos.as_tuple(), self.longest_keep_time, self.qte_detail_log)
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
