"""GDI 资源所有权与 BGR 拷贝回归；使用假 API，不读取屏幕。"""
import ctypes
import unittest
from unittest.mock import Mock, patch

import numpy as np
from feedback_capture import FeedbackCapture, _BitmapInfoHeader
from utils import Rect


class FeedbackCaptureTests(unittest.TestCase):
    def backend(self):
        gdi, user = Mock(), Mock()
        user.GetDC.return_value = 11
        gdi.CreateCompatibleDC.return_value = 22
        gdi.SelectObject.return_value = 44
        pixels = (ctypes.c_uint8 * 8)(1, 2, 3, 255, 4, 5, 6, 255)
        def create(screen, header, usage, target, section, offset):
            info = ctypes.cast(header, ctypes.POINTER(_BitmapInfoHeader)).contents
            self.assertEqual((info.width, info.height, info.bit_count), (2, -1, 32))
            ctypes.cast(target, ctypes.POINTER(ctypes.c_void_p)).contents.value = ctypes.addressof(pixels)
            return 33
        gdi.CreateDIBSection.side_effect = create
        return gdi, user, pixels

    def test_bgr_is_owned_copy_and_handles_release_once(self):
        gdi, user, pixels = self.backend()
        with patch("feedback_capture.ctypes.WinDLL", side_effect=[gdi, user]):
            camera = FeedbackCapture(Rect(-20, 10, -18, 11))
            with camera:
                frame = camera.grab()
                np.testing.assert_array_equal(frame, [[[1, 2, 3], [4, 5, 6]]])
                pixels[0] = 99
                self.assertEqual(frame[0, 0, 0], 1)
                gdi.BitBlt.assert_called_once_with(22, 0, 0, 2, 1, 11, -20, 10, 0x40CC0020)
            camera.__exit__(None, None, None)
        gdi.DeleteObject.assert_called_once_with(33)
        gdi.DeleteDC.assert_called_once_with(22)
        user.ReleaseDC.assert_called_once_with(None, 11)

    def test_partial_initialization_releases_screen_dc(self):
        gdi, user, _ = self.backend()
        gdi.CreateCompatibleDC.return_value = 0
        with patch("feedback_capture.ctypes.WinDLL", side_effect=[gdi, user]):
            with self.assertRaises(OSError):
                with FeedbackCapture(Rect(0, 0, 2, 1)):
                    self.fail("must not enter")
        user.ReleaseDC.assert_called_once_with(None, 11)
        gdi.DeleteObject.assert_not_called()

    def test_failed_grab_releases_all_native_objects(self):
        gdi, user, _ = self.backend()
        gdi.BitBlt.return_value = 0
        with patch("feedback_capture.ctypes.WinDLL", side_effect=[gdi, user]):
            with self.assertRaises(OSError):
                with FeedbackCapture(Rect(0, 0, 2, 1)) as camera:
                    camera.grab()
        gdi.DeleteObject.assert_called_once_with(33)
        gdi.DeleteDC.assert_called_once_with(22)
        user.ReleaseDC.assert_called_once_with(None, 11)
