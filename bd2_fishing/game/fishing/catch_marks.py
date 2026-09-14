"""读取结算奖励的尺寸标签与等级角标，不从鱼名或参考尺寸推断。"""

import re
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class SizeMarks:
    kind: str = "unknown"
    new_record: bool = False


def parse_size_marks(texts):
    flags = set()
    new_record = False
    for item in texts:
        if item.score < 0.90:
            continue
        token = re.sub(r"\s+", "", item.text).upper()
        # OCR 可能把同一行的厘米数和右侧标签合并，不能匹配说明文字中的子串。
        token = re.sub(r"^\d+(?:\.\d+)?CM", "", token)
        token = token.rstrip(".!！")
        if token in {"MAX", "MAXIMUMSIZE"}:
            flags.add("max")
        elif token in {"MIN", "MINIMUMSIZE"}:
            flags.add("min")
        elif token == "NEWRECORD":
            new_record = True
    return SizeMarks(next(iter(flags)) if len(flags) == 1 else "unknown", new_record)


def _corner_count(hsv, lower, upper):
    mask = cv2.inRange(hsv, np.array(lower, np.uint8), np.array(upper, np.uint8))
    # 缩放插值会把相邻两个角标接上一像素细桥；去桥后仍要求独立实心角标。
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _, stats, centers = cv2.connectedComponentsWithStats(mask)
    dots = []
    for index in range(1, count):
        _, _, width, height, area = stats[index]
        if 4 <= area <= 45 and 2 <= width <= 8 and 2 <= height <= 8:
            dots.append(centers[index])
    return sorted(dots, key=lambda point: point[0])


def read_reward_grade(frame, *, confirmed_catch=False):
    """已确认奖励页内，角标个数与底框颜色一致才接受 1/2 级。

    彩色三级尚无本机成功原图，返回未知，不按已知鱼种补填观测值。
    """
    if not confirmed_catch or frame is None or frame.ndim != 3:
        return None, "unknown"
    height, width = frame.shape[:2]
    if width < 600 or height < 350 or abs(width / height - 945 / 532) > 0.04:
        return None, "unknown"
    # 只缩放小型奖励卡片，避开角色、粒子及文字；保留 BGR -> HSV 约定。
    left, top = round(width * 388 / 945), round(height * 54 / 532)
    right, bottom = round(width * 430 / 945), round(height * 97 / 532)
    card = cv2.resize(frame[top:bottom, left:right, :3], (42, 43))
    hsv = cv2.cvtColor(card, cv2.COLOR_BGR2HSV)
    corner = hsv[1:12, 21:42]
    background = hsv[34:41, 2:10]
    matches = []
    for grade, color, lower, upper in (
        (1, "green", (38, 65, 100), (82, 255, 255)),
        (2, "blue", (88, 65, 100), (115, 255, 255)),
    ):
        dots = _corner_count(corner, lower, upper)
        pixels = cv2.inRange(background, np.array(lower, np.uint8), np.array(upper, np.uint8))
        if len(dots) != grade or np.count_nonzero(pixels) / pixels.size < 0.35:
            continue
        if grade == 2 and (
            not 4 <= dots[1][0] - dots[0][0] <= 9 or abs(dots[1][1] - dots[0][1]) > 2
        ):
            continue
        matches.append((grade, color))
    return matches[0] if len(matches) == 1 else (None, "unknown")
