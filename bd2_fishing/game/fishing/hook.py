"""等待咬钩的局部信号；复用原黄色像素门槛，不判断 QTE 技能惊叹号。"""

import cv2

from bd2_fishing.perception import image as vision
from bd2_fishing.runtime.geometry import Rect, scale_pixel_threshold

BITE_PIXEL_THRESHOLD = 220
BITE_TIMEOUT_SECONDS = 15


class HookReader:
    def __init__(self, config, window):
        self.window = window
        self.region = vision.build_region_from_config(
            config, "hook", Rect(0, 0, window.width, window.height)
        )
        self.color = vision.read_hsv_range(config, "hook", "hook")
        self.threshold = scale_pixel_threshold(
            BITE_PIXEL_THRESHOLD, vision.build_pixel_threshold_scale(config, window)
        )

    def inspect(self, frame):
        if frame is None or frame.shape[:2] != (self.window.height, self.window.width):
            return False, 0
        rect = self.region
        hsv = cv2.cvtColor(frame[rect.top : rect.bottom, rect.left : rect.right], cv2.COLOR_BGR2HSV)
        pixels = cv2.countNonZero(cv2.inRange(hsv, self.color.lower, self.color.upper))
        return pixels > self.threshold, pixels
