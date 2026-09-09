"""在每次游戏输入前检查停止状态，并提供可靠的按键释放。"""

from __future__ import annotations

import ctypes
import math

import pydirectinput as _input
import win32api

from bd2_fishing.infrastructure.windows.display import normalize_virtual_point
from bd2_fishing.runtime import control as run_control


def press(*args, **kwargs):
    return run_control.call_input(_input.press, *args, **kwargs)


def press_qte(hold_seconds, settle_seconds):
    """自定义 QTE 单键时序；等待不持输入锁，停止期间仅允许释放按键。"""
    if (
        not math.isfinite(hold_seconds)
        or not 0.005 <= hold_seconds <= 0.5
        or not math.isfinite(settle_seconds)
        or not 0 <= settle_seconds <= 1
    ):
        raise ValueError("QTE 输入时延超出允许范围")
    try:
        if not run_control.call_input(_input.keyDown, "space", _pause=False):
            raise RuntimeError("QTE 按键未被系统接受")
        run_control.sleep(hold_seconds)
    finally:
        run_control.call_release(_release_qte_key)
    run_control.sleep(settle_seconds)
    return True


def _release_qte_key():
    # 与停止释放共用输入锁，避免并发恢复全局 FAILSAFE 时覆盖彼此状态。
    previous = _input.FAILSAFE
    try:
        _input.FAILSAFE = False
        _input.keyUp("space", _pause=False)
    finally:
        _input.FAILSAFE = previous


def keyDown(*args, **kwargs):
    return run_control.call_input(_input.keyDown, *args, **kwargs)


def keyUp(*args, **kwargs):
    return run_control.call_input(_input.keyUp, *args, **kwargs)


def _move_virtual(x, y):
    _input.failSafeCheck()
    current_x, current_y = _input.position()
    x = current_x if x is None else int(x)
    y = current_y if y is None else int(y)
    left, top, width, height = (win32api.GetSystemMetrics(i) for i in (76, 77, 78, 79))
    nx, ny = normalize_virtual_point(x, y, (left, top, left + width, top + height))
    extra = ctypes.c_ulong(0)
    payload = _input.Input_I()
    # MOUSEEVENTF_VIRTUALDESK 将绝对坐标映射到所有屏幕，而非仅主屏。
    payload.mi = _input.MouseInput(nx, ny, 0, 0x0001 | 0x8000 | 0x4000, 0, ctypes.pointer(extra))
    command = _input.Input(ctypes.c_ulong(0), payload)
    if _input.SendInput(1, ctypes.pointer(command), ctypes.sizeof(command)) != 1:
        raise RuntimeError("鼠标移动未被系统接受，请检查游戏与脚本权限是否一致")


def moveTo(
    x=None, y=None, duration=None, tween=None, logScreenshot=False, _pause=True, relative=False
):
    if relative:
        return run_control.call_input(
            _input.moveTo,
            x,
            y,
            duration=duration,
            tween=tween,
            logScreenshot=logScreenshot,
            _pause=_pause,
            relative=True,
        )
    run_control.call_input(_move_virtual, x, y)
    if _pause:
        run_control.sleep(_input.PAUSE)


def click(x=None, y=None, *args, **kwargs):
    if x is not None or y is not None:
        moveTo(x, y, _pause=False)
    return run_control.call_input(_input.click, None, None, *args, **kwargs)


def release_inputs():
    previous = _input.FAILSAFE
    try:
        _input.FAILSAFE = False
        for key in ("space", "up", "t"):
            _input.keyUp(key, _pause=False)
        _input.mouseUp(_pause=False)
    finally:
        _input.FAILSAFE = previous
