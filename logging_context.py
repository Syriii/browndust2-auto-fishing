"""日志轮次关联；同步流程使用上下文，后台任务显式携带轮次编号。"""
from contextlib import contextmanager
from contextvars import ContextVar
import itertools
import logging
import uuid

_round = ContextVar("fishing_log_round", default=None)
_process_id = uuid.uuid4().hex[:8]
_sequence = itertools.count(1)


def current_round_id():
    return _round.get()


@contextmanager
def fishing_round(round_id=None):
    round_id = round_id or f"{_process_id}-{next(_sequence):03d}"
    token = _round.set(round_id)
    try:
        yield round_id
    finally:
        _round.reset(token)


class RoundLogger(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = dict(kwargs.get("extra", {}))
        round_id = self.extra.get("round_id") or current_round_id()
        if round_id:
            extra["round_id"] = round_id
            msg = f"[轮次={round_id}] {msg}"
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name, round_id=None):
    return RoundLogger(logging.getLogger(name), {"round_id": round_id})
