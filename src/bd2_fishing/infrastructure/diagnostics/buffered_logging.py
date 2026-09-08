"""有界的后台日志输出；慢文件系统不阻塞游戏控制线程。"""

from __future__ import annotations

import copy
import logging
import queue
import threading


class BufferedHandler(logging.Handler):
    """拥有输出 handler 和工作线程；关闭时最多等待两秒排空。

    调用方只固定消息与入队，不格式化 traceback、不写文件。队列满时
    丢弃新记录，后台明确输出丢弃计数；不回退为控制线程同步写盘。
    """

    def __init__(self, target: logging.Handler, *, capacity: int = 4096):
        if capacity < 1:
            raise ValueError("Log capacity must be positive")
        super().__init__(target.level)
        self.target = target
        self._queue = queue.Queue(maxsize=capacity)
        # 为结果/错误日志保留容量；详细采样不能占满整个队列。
        self._detail_limit = capacity - min(256, max(1, capacity // 8)) if capacity > 1 else 1
        self._state_lock = threading.Lock()
        self._stopping = threading.Event()
        self._lost_pending = 0
        self.dropped_records = 0
        self._thread = threading.Thread(target=self._run, name="file-log-writer", daemon=True)
        self._thread.start()

    def emit(self, record):
        # 固定消息，避免调用方随后修改 args；保留异常和轮次信息给后台。
        snapshot = copy.copy(record)
        snapshot.msg = record.getMessage()
        snapshot.args = None
        with self._state_lock:
            if self._stopping.is_set():
                return
            try:
                if record.levelno < logging.INFO and self._queue.qsize() >= self._detail_limit:
                    raise queue.Full
                self._queue.put_nowait(snapshot)
            except queue.Full:
                self._lost_pending += 1
                self.dropped_records += 1

    def _report_loss(self):
        with self._state_lock:
            lost, self._lost_pending = self._lost_pending, 0
        if lost:
            record = logging.LogRecord(
                __name__,
                logging.WARNING,
                __file__,
                0,
                "文件日志队列容量不足：丢弃 %d 条新记录；游戏控制未等待写盘",
                (lost,),
                None,
            )
            self.target.handle(record)

    def _run(self):
        try:
            while not self._stopping.is_set() or not self._queue.empty():
                try:
                    item = self._queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    if isinstance(item, threading.Event):
                        self.target.flush()
                        item.set()
                    else:
                        self.target.handle(item)
                    self._report_loss()
                finally:
                    self._queue.task_done()
            self._report_loss()
        finally:
            self.target.close()

    def flush(self):
        """用于退出或显式检查，不从逐帧控制路径调用。"""
        if self._stopping.is_set() or not self._thread.is_alive():
            return
        completed = threading.Event()
        try:
            self._queue.put(completed, timeout=2)
        except queue.Full:
            return
        completed.wait(2)

    def close(self):
        with self._state_lock:
            self._stopping.set()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)
        # 输出 handler 由工作线程关闭，不能与尚未完成的写盘并发关闭。
        super().close()
