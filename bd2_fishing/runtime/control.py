"""runtime.control：从现有实现分离的职责模块。"""

from __future__ import annotations

import builtins
import logging
import sys
import threading
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)


_local = threading.local()


class RunStopped(BaseException):
    """停止不是识别错误，不能被 OCR 的 except Exception 吞掉。"""


class RunControl:
    def __init__(self):
        self.stopped = threading.Event()
        self.input_lock = threading.Lock()
        self.phase = "启动中"

    def check(self):
        if self.stopped.is_set():
            raise RunStopped()

    def stop(self, release_inputs):
        self.stopped.set()
        with self.input_lock:
            release_inputs()


@contextmanager
def use_control(control):
    previous = getattr(_local, "control", None)
    _local.control = control
    try:
        yield
    finally:
        _local.control = previous


def checkpoint():
    control = getattr(_local, "control", None)
    if control is not None:
        control.check()
    guard = getattr(_local, "input_guard", None)
    if guard is not None:
        guard()


def set_status(phase):
    control = getattr(_local, "control", None)
    if control is not None:
        control.phase = phase


@contextmanager
def use_input_guard(guard):
    """窗口检查与工作线程绑定；同时覆盖截图循环及真实输入之前。"""
    previous = getattr(_local, "input_guard", None)
    _local.input_guard = guard
    try:
        checkpoint()
        yield
    finally:
        _local.input_guard = previous


def sleep(seconds):
    control = getattr(_local, "control", None)
    if control is None:
        return time.sleep(seconds)
    if seconds < 0:
        raise ValueError("sleep length must be non-negative")
    if getattr(_local, "input_guard", None) is not None:
        deadline = time.monotonic() + seconds
        while True:
            checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if control.stopped.wait(min(remaining, 0.05)):
                raise RunStopped()
    if control.stopped.wait(seconds):
        raise RunStopped()


def call_input(action, *args, **kwargs):
    control = getattr(_local, "control", None)
    if control is None:
        checkpoint()
        return action(*args, **kwargs)
    with control.input_lock:
        checkpoint()
        return action(*args, **kwargs)


def call_release(action, *args, **kwargs):
    """仅供输入适配器释放按键；与停止释放串行，但不能被停止或失焦检查拦截。"""
    control = getattr(_local, "control", None)
    if control is None:
        return action(*args, **kwargs)
    with control.input_lock:
        return action(*args, **kwargs)


def console_input(prompt):
    """供实机工具手动选地图，等待输入期间仍响应取消。"""
    if getattr(_local, "control", None) is None:
        return builtins.input(prompt)
    if sys.stdin is None or not sys.stdin.isatty():
        raise RuntimeError("OCR 未识别地点，请在控制台中重新启动并选择地点")
    import msvcrt

    print(prompt, end="", flush=True)
    chars = []
    extended = False
    while True:
        checkpoint()
        if not msvcrt.kbhit():
            sleep(0.02)
            continue
        char = msvcrt.getwch()
        if extended:
            extended = False
            continue
        if char in ("\x00", "\xe0"):
            extended = True
        elif char in ("\r", "\n"):
            print(flush=True)
            return "".join(chars)
        elif char == "\x03":
            raise RunStopped()
        elif char == "\b":
            if chars:
                chars.pop()
                print("\b \b", end="", flush=True)
        elif char.isprintable():
            chars.append(char)
            print(char, end="", flush=True)
