"""多显示器、任务栏与屏幕边缘的程序窗口定位回归。"""

import unittest
from unittest.mock import patch

from bd2_fishing.infrastructure.windows.desktop_placement import centered_bounds, client_size_limit


class DesktopPlacementTests(unittest.TestCase):
    def test_client_limit_reserves_native_titlebar_and_borders_on_offset_monitor(self):
        with (
            patch(
                "bd2_fishing.infrastructure.windows.desktop_placement._placement_context",
                return_value=(1, (-1366, -100, 0, 628), None),
            ),
            patch(
                "bd2_fishing.infrastructure.windows.desktop_placement.win32gui.GetWindowRect",
                return_value=(0, 0, 1316, 939),
            ),
            patch(
                "bd2_fishing.infrastructure.windows.desktop_placement.win32gui.GetClientRect",
                return_value=(0, 0, 1300, 900),
            ),
        ):
            self.assertEqual(client_size_limit(1), (1350, 689))

    def test_center_on_negative_coordinate_monitor(self):
        self.assertEqual(centered_bounds((820, 730), (-1920, -100, 0, 940)), (-1370, 55, 820, 730))

    def test_parent_center_is_clamped_above_taskbar(self):
        work = (1920, 0, 3840, 1040)
        self.assertEqual(
            centered_bounds((820, 730), work, (3300, 700, 3840, 1040)), (3020, 310, 820, 730)
        )

    def test_oversized_window_fits_short_monitor(self):
        self.assertEqual(centered_bounds((900, 780), (0, 0, 800, 600)), (0, 0, 800, 600))

    def test_dialog_centers_on_parent_instead_of_monitor(self):
        self.assertEqual(
            centered_bounds((820, 730), (0, 0, 1920, 1040), (200, 100, 1116, 879)),
            (248, 124, 820, 730),
        )
