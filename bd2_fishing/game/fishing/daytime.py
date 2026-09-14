"""读取游戏钟面亮起的太阳／月亮；不按系统时间或场景天空推断。"""

import cv2
import numpy as np


def read_daytime(frame):
    if frame is None or frame.ndim != 3:
        return "unknown"
    height, width = frame.shape[:2]
    if width < 600 or height < 350 or abs(width / height - 945 / 532) > 0.04:
        return "unknown"
    clock = frame[
        round(height * 44 / 532) : round(height * 84 / 532),
        round(width * 72 / 945) : round(width * 97 / 945),
    ]
    hsv = cv2.cvtColor(cv2.resize(clock, (25, 40)), cv2.COLOR_BGR2HSV)
    sun, moon = hsv[:19], hsv[21:40, 1:24]
    gold = np.count_nonzero(cv2.inRange(sun, (12, 90, 150), (42, 255, 255)))
    light = np.count_nonzero(cv2.inRange(moon, (0, 0, 190), (179, 255, 255)))
    glow = np.count_nonzero(cv2.inRange(moon, (75, 60, 110), (120, 255, 255)))
    day, night = gold >= 25, light >= 55 and glow >= 40
    if day == night:
        return "unknown"
    return "day" if day else "night"
