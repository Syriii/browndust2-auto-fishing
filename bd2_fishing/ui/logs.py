"""有界的界面日志副本；格式化在主线程进行，不占用 QTE 输入线程。"""

import copy
import itertools
import logging
import queue
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LogEntry:
    created: float
    level: int
    message: str
    diagnostic: str
    diagnostic_only: bool = False
    sequence: int = 0

    def display(self, detailed=False):
        symbol, label = (
            ("!", "错误")
            if self.level >= logging.ERROR
            else ("△", "注意")
            if self.level >= logging.WARNING
            else ("·", "诊断")
            if self.level < logging.INFO
            else ("●", "进展")
        )
        stamp = datetime.fromtimestamp(self.created).strftime("%H:%M:%S")
        return f"{stamp}  {symbol} {label}  {self.diagnostic if detailed else self.message}"


class UILogHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        # 高频诊断不能挤占正常进展和警告的空间。
        self.messages = queue.Queue(maxsize=1500)
        self.diagnostics = queue.Queue(maxsize=500)
        self.skipped = 0
        self.sequence = itertools.count()
        self.setFormatter(logging.Formatter("%(name)s: %(message)s"))

    def emit(self, record):
        try:
            target = (
                self.messages
                if record.levelno >= logging.INFO and not getattr(record, "diagnostic_only", False)
                else self.diagnostics
            )
            snapshot = copy.copy(record)
            snapshot.ui_sequence = next(self.sequence)
            target.put_nowait(snapshot)
        except queue.Full:
            self.skipped += 1
        except Exception:
            self.handleError(record)

    def drain(self, limit=100):
        entries = []
        for source in (self.messages, self.diagnostics):
            for _ in range(limit):
                try:
                    record = source.get_nowait()
                except queue.Empty:
                    break
                try:
                    message = getattr(record, "user_message", None)
                    if message is None:
                        message = getattr(record, "plain_message", record.msg)
                        if record.args:
                            message = str(message) % record.args
                    entries.append(
                        LogEntry(
                            record.created,
                            record.levelno,
                            str(message),
                            self.format(record),
                            getattr(record, "diagnostic_only", False),
                            record.ui_sequence,
                        )
                    )
                except Exception as exc:
                    # 单条第三方日志损坏不能终止 UI 轮询和停止按钮更新。
                    entries.append(
                        LogEntry(
                            record.created,
                            logging.WARNING,
                            "一条运行记录格式有误，后续记录仍会继续显示。",
                            f"{record.name}: 日志格式化失败（{type(exc).__name__}）",
                            sequence=record.ui_sequence,
                        )
                    )
        return sorted(entries, key=lambda entry: (entry.created, entry.sequence))
