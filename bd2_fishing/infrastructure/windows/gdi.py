"""只读 GDI 小区域采集，供 QTE 反馈观察使用，不占用第二个 DXGI duplication。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes as w

import numpy as np


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("width", w.LONG),
        ("height", w.LONG),
        ("planes", w.WORD),
        ("bit_count", w.WORD),
        ("compression", w.DWORD),
        ("size_image", w.DWORD),
        ("x_ppm", w.LONG),
        ("y_ppm", w.LONG),
        ("used", w.DWORD),
        ("important", w.DWORD),
    ]


class FeedbackCapture:
    """仅截取指定绝对屏幕 ROI；所有原生资源在采集线程内创建和释放。"""

    def __init__(self, region):
        self.region = region
        self.screen = self.memory = self.bitmap = self.previous = None
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        signatures = [
            (self.user.GetDC, [w.HWND], w.HDC),
            (self.user.ReleaseDC, [w.HWND, w.HDC], ctypes.c_int),
            (self.gdi.CreateCompatibleDC, [w.HDC], w.HDC),
            (self.gdi.DeleteDC, [w.HDC], w.BOOL),
            (self.gdi.SelectObject, [w.HDC, w.HANDLE], w.HANDLE),
            (self.gdi.DeleteObject, [w.HANDLE], w.BOOL),
            (
                self.gdi.CreateDIBSection,
                [
                    w.HDC,
                    ctypes.c_void_p,
                    w.UINT,
                    ctypes.POINTER(ctypes.c_void_p),
                    w.HANDLE,
                    w.DWORD,
                ],
                w.HANDLE,
            ),
            (
                self.gdi.BitBlt,
                [
                    w.HDC,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    w.HDC,
                    ctypes.c_int,
                    ctypes.c_int,
                    w.DWORD,
                ],
                w.BOOL,
            ),
            (self.gdi.GdiFlush, [], w.BOOL),
        ]
        for function, args, result in signatures:
            function.argtypes, function.restype = args, result

    def __enter__(self):
        try:
            self.screen = self.user.GetDC(None)
            self.memory = self.gdi.CreateCompatibleDC(self.screen) if self.screen else None
            if not self.memory:
                raise ctypes.WinError(ctypes.get_last_error())
            header = _BitmapInfoHeader(
                size=ctypes.sizeof(_BitmapInfoHeader),
                width=self.region.width,
                height=-self.region.height,
                planes=1,
                bit_count=32,
            )
            pixels = ctypes.c_void_p()
            self.bitmap = self.gdi.CreateDIBSection(
                self.screen, ctypes.byref(header), 0, ctypes.byref(pixels), None, 0
            )
            if not self.bitmap or not pixels.value:
                raise ctypes.WinError(ctypes.get_last_error())
            self.previous = self.gdi.SelectObject(self.memory, self.bitmap)
            if not self.previous or self.previous == ctypes.c_void_p(-1).value:
                self.previous = None
                raise ctypes.WinError(ctypes.get_last_error())
            buffer = (ctypes.c_uint8 * (self.region.width * self.region.height * 4)).from_address(
                pixels.value
            )
            self.pixels = np.ctypeslib.as_array(buffer).reshape(
                self.region.height, self.region.width, 4
            )
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def grab(self):
        # SRCCOPY | CAPTUREBLT：包含游戏窗口的合成内容，返回 BGR 而不是 RGB。
        if not self.gdi.BitBlt(
            self.memory,
            0,
            0,
            self.region.width,
            self.region.height,
            self.screen,
            self.region.left,
            self.region.top,
            0x40CC0020,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        self.gdi.GdiFlush()
        return self.pixels[:, :, :3].copy()

    def __exit__(self, *args):
        if self.previous:
            self.gdi.SelectObject(self.memory, self.previous)
            self.previous = None
        if self.bitmap:
            self.gdi.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.memory:
            self.gdi.DeleteDC(self.memory)
            self.memory = None
        if self.screen:
            self.user.ReleaseDC(None, self.screen)
            self.screen = None
