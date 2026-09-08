"""游戏聚焦和会话期间的电源请求；不修改用户的系统电源设置。"""

from contextlib import contextmanager
import ctypes
import logging

import win32gui
import run_control

log = logging.getLogger(__name__)


def input_desktop_available():
    user32 = ctypes.windll.user32
    user32.OpenInputDesktop.argtypes = [ctypes.c_uint, ctypes.c_bool, ctypes.c_uint]
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    desktop = user32.OpenInputDesktop(0, False, 0x0101)
    if not desktop:
        return False
    user32.CloseDesktop(desktop)
    return True


def focus_game(title):
    if not input_desktop_available():
        raise RuntimeError("当前桌面不可交互；请解锁 Windows 后重新开始")
    hwnd = win32gui.FindWindow(None, title)
    if not hwnd:
        raise RuntimeError(f"未找到游戏窗口：{title}，请先打开游戏")
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:
        log.debug("Windows 未接受聚焦请求: %s", exc)
    for _ in range(20):
        run_control.checkpoint()
        if win32gui.GetForegroundWindow() == hwnd:
            log.info("游戏已聚焦，准备初始化")
            return hwnd
        run_control.sleep(0.05)
    raise RuntimeError("未能自动聚焦游戏；请确认游戏可正常显示后重试，或检查游戏与程序权限是否一致")


@contextmanager
def keep_awake(enabled):
    if not enabled:
        yield
        return
    setter = ctypes.windll.kernel32.SetThreadExecutionState
    setter.argtypes = [ctypes.c_uint]
    setter.restype = ctypes.c_uint
    previous = setter(0x80000003)  # CONTINUOUS | SYSTEM_REQUIRED | DISPLAY_REQUIRED
    if not previous:
        log.warning("保持唤醒请求失败，系统仍可能自动息屏或睡眠")
    else:
        log.info("本次任务保持屏幕和电脑唤醒；锁屏或主动睡眠仍会中断任务")
    try:
        yield
    finally:
        if previous:
            setter(previous)
            log.info("已恢复本线程原有电源请求")
