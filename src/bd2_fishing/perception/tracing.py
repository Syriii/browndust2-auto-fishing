"""通用 OCR 识别上下文和日志过滤，不绑定具体 OCR 引擎。"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar

from bd2_fishing.runtime.context import current_round_id

_ocr_context = ContextVar("ocr_log_context", default="未指定场景")


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
        record.msg = (
            f"[OCR {_ocr_context.get()} {record.filename}:{record.lineno}] {record.getMessage()}"
        )
        if current_round_id():
            record.round_id = current_round_id()
            record.msg = f"[轮次={record.round_id}] {record.msg}"
        record.args = ()
        return True
