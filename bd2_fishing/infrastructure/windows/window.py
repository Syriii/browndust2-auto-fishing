"""infrastructure.windows.window：从现有实现分离的职责模块。"""

from __future__ import annotations

import ctypes
import logging

import win32gui

from bd2_fishing.runtime.geometry import Rect

log = logging.getLogger(__name__)


def enable_dpi_awareness():
    """使用每显示器物理像素；线程设置兼容已由宿主设置过进程 DPI 的情况。"""
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except AttributeError:
            user32.SetProcessDPIAware()


def _client_region(hwnd):
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    _, _, width, height = win32gui.GetClientRect(hwnd)
    return Rect(left, top, left + width, top + height)


class WindowGuard:
    """窗口几何变化后停止本轮，避免旧 ROI 和旧点击位置继续生效。"""

    def __init__(self, title, region, require_foreground=False):
        self.hwnd = win32gui.FindWindow(None, title)
        self.region = region
        self.require_foreground = require_foreground

    def __call__(self):
        if self.require_foreground:
            from bd2_fishing.infrastructure.windows.session import input_desktop_available
            from bd2_fishing.runtime.control import RunStopped

            if not input_desktop_available():
                raise RunStopped("桌面已锁定或不可交互；解锁后请重新开始")
            if win32gui.GetForegroundWindow() != self.hwnd:
                raise RunStopped("游戏已失去焦点，任务停止；重新开始时会再次聚焦游戏")
        if not self.hwnd or not win32gui.IsWindow(self.hwnd) or win32gui.IsIconic(self.hwnd):
            raise RuntimeError("游戏窗口已关闭或最小化；恢复窗口后点击开始钓鱼 重新开始")
        if _client_region(self.hwnd) != self.region:
            raise RuntimeError("游戏窗口已移动或缩放；请放置完成后点击开始钓鱼 重新定位")


def get_window_region(window_title: str) -> Rect | None:
    """获取窗口客户区的屏幕绝对坐标，不包含标题栏和边框。"""
    hwnd = win32gui.FindWindow(None, window_title)
    if not hwnd:
        log.warning("未找到游戏窗口，请打开游戏并恢复为可见窗口。")
        return None

    if win32gui.IsIconic(hwnd):
        raise RuntimeError("游戏窗口已最小化，请恢复后点击开始钓鱼 启动")
    region = _client_region(hwnd)
    if region.width <= 0 or region.height <= 0:
        raise RuntimeError("游戏客户区尺寸无效，请恢复窗口后重试")
    return region
