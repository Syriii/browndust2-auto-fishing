"""只定位程序自身窗口，使用所在显示器的可用区域（排除任务栏）。"""

import win32api
import win32con
import win32gui


def centered_bounds(size, work_area, anchor=None):
    left, top, right, bottom = work_area
    width, height = min(size[0], right - left), min(size[1], bottom - top)
    a_left, a_top, a_right, a_bottom = anchor or work_area
    x = max(left, min((a_left + a_right - width) // 2, right - width))
    y = max(top, min((a_top + a_bottom - height) // 2, bottom - height))
    return x, y, width, height


def _placement_context(handle, parent_handle):
    # Tk 的 winfo_id 是客户窗口；顶层装饰与边框属于根 HWND。
    handle = win32gui.GetAncestor(handle, win32con.GA_ROOT)
    anchor = None
    if parent_handle is not None:
        parent_handle = win32gui.GetAncestor(parent_handle, win32con.GA_ROOT)
        anchor = win32gui.GetWindowRect(parent_handle)
        monitor = win32api.MonitorFromWindow(parent_handle, win32con.MONITOR_DEFAULTTONEAREST)
    else:
        monitor = win32api.MonitorFromPoint(
            win32api.GetCursorPos(), win32con.MONITOR_DEFAULTTONEAREST
        )
    work_area = win32api.GetMonitorInfo(monitor)["Work"]
    return handle, work_area, anchor


def client_size_limit(handle, parent_handle=None):
    handle, (left, top, right, bottom), _ = _placement_context(handle, parent_handle)
    x1, y1, x2, y2 = win32gui.GetWindowRect(handle)
    cx1, cy1, cx2, cy2 = win32gui.GetClientRect(handle)
    border_width = (x2 - x1) - (cx2 - cx1)
    border_height = (y2 - y1) - (cy2 - cy1)
    return max(1, right - left - border_width), max(1, bottom - top - border_height)


def center_window(handle, parent_handle=None):
    handle, work_area, anchor = _placement_context(handle, parent_handle)
    left, top, right, bottom = win32gui.GetWindowRect(handle)
    bounds = centered_bounds((right - left, bottom - top), work_area, anchor)
    win32gui.SetWindowPos(handle, 0, *bounds, win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
