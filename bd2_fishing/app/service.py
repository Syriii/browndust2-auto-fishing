"""app.service：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging
import threading

from bd2_fishing.runtime.control import RunControl, RunStopped, checkpoint, use_control

log = logging.getLogger(__name__)


class TaskController:
    def __init__(self, target, release_inputs):
        self.target = target
        self.release_inputs = release_inputs
        self.worker = None
        self.control = None
        self.last_error = None
        self.last_stop_reason = "尚未启动"

    @property
    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def stop(self):
        if self.running:
            self.control.stop(self.release_inputs)
            log.info("已请求停止，正在释放资源")

    def start(self):
        if self.running:
            return
        self.last_error = None
        self.last_stop_reason = ""
        self.control = RunControl()
        self.worker = threading.Thread(
            target=self._run, args=(self.control,), name="fishing-worker", daemon=True
        )
        log.info("钓鱼任务启动；点击停止任务结束运行")
        self.worker.start()

    def _run(self, control):
        try:
            with use_control(control):
                checkpoint()
                self.target()
        except RunStopped as exc:
            self.last_stop_reason = str(exc) or "已停止"
        except Exception as exc:
            self.last_error = str(exc)
            log.exception(">>> 钓鱼任务异常，已返回待机；排查后可点击开始钓鱼重试")
        finally:
            control.stop(self.release_inputs)
            if not self.last_stop_reason:
                self.last_stop_reason = "本次任务已结束"
            log.info("已停止，按键已释放；原因=%s", self.last_error or self.last_stop_reason)

    def close(self):
        if self.control is not None:
            self.control.stop(self.release_inputs)
        if self.worker is not None:
            self.worker.join(timeout=3)
