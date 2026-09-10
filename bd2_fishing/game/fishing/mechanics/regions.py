"""QTE 条内的机制区域；纯图像定位，不执行输入或把颜色等同于技能身份。"""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class GreenTarget:
    left: int
    right: int  # exclusive
    entry: tuple[int, int] | None = None


@dataclass(frozen=True)
class MechanismRegions:
    green_present: bool
    green: GreenTarget | None
    blocked: np.ndarray
    purple_spans: tuple[tuple[int, int], ...]
    red_spans: tuple[tuple[int, int], ...]
    bubble_spans: tuple[tuple[int, int], ...] = ()

    def ordinary_pixels(self, hsv):
        if not self.bubble_spans:
            return hsv
        result = hsv.copy()
        margin = max(2, hsv.shape[0] // 4)
        for left, right in self.bubble_spans:
            result[:, max(0, left - margin) : min(hsv.shape[1], right + margin)] = 0
        return result

    def mask_target(self, mask):
        result = mask.copy()
        result[:, self.blocked] = 0
        # 球体的金色/蓝色描边不是普通黄/蓝目标，球体由独立单击控制器处理。
        for left, right in self.bubble_spans:
            result[:, left:right] = 0
        return result


def _spans(columns):
    edges = np.diff(np.r_[False, columns, False].astype(np.int8))
    return tuple(zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist()))


def _bubble_spans(hsv, green):
    """已采样泡泡球：紧凑绿环、亮色球面与低填充率；不把长绿条当作球。"""
    height, width = green.shape
    columns = np.any(green, axis=0).astype(np.uint8)[None, :]
    joined = cv2.morphologyEx(
        columns, cv2.MORPH_CLOSE, np.ones((1, max(3, round(height * 0.6) | 1)), np.uint8)
    )[0]
    white = cv2.inRange(hsv, (0, 0, 190), (180, 100, 255))
    result = []
    for left, right in _spans(joined.astype(bool)):
        span = right - left
        if not max(8, height * 0.65) <= span <= height * 1.9:
            continue
        ys, _ = np.nonzero(green[:, left:right])
        if len(ys) < max(8, height) or np.ptp(ys) + 1 < height * 0.6:
            continue
        if len(ys) / (height * span) >= 0.6 or cv2.countNonZero(white[:, left:right]) < height:
            continue
        margin = max(2, round(height * 0.15))
        result.append((max(0, left - margin), min(width, right + margin)))
    return tuple(result)


def read_mechanism_regions(hsv, margin=3):
    """同帧小 ROI 筛选色区，红/紫只做局部避让，不产生主动消除按键。"""
    height, width = hsv.shape[:2]
    masks = {
        "green": cv2.inRange(hsv, (40, 100, 100), (85, 255, 255)),
        "purple": cv2.inRange(hsv, (125, 100, 150), (169, 255, 255)),
        "red": cv2.bitwise_or(
            cv2.inRange(hsv, (0, 100, 100), (10, 255, 255)),
            cv2.inRange(hsv, (170, 100, 100), (180, 255, 255)),
        ),
    }
    bubbles = _bubble_spans(hsv, masks["green"])
    for left, right in bubbles:
        masks["green"][:, left:right] = 0
    # 牙齿的浅粉边缘饱和度较低：由高饱和红色种子限定连通区域，避免直接放宽全图红色阈值。
    if cv2.countNonZero(masks["red"]) >= 3:
        pale = cv2.bitwise_or(
            cv2.inRange(hsv, (0, 25, 100), (10, 255, 255)),
            cv2.inRange(hsv, (170, 25, 100), (180, 255, 255)),
        )
        pale = cv2.morphologyEx(pale, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(pale)
        expanded = np.zeros_like(pale)
        for label in range(1, count):
            if stats[label, cv2.CC_STAT_AREA] >= 8 and np.any(masks["red"][labels == label]):
                expanded[labels == label] = 255
        masks["red"] = expanded
    spans = {}
    for name, mask in masks.items():
        columns = np.count_nonzero(mask, axis=0) >= max(2, round(height * 0.20))
        # 仅填补窄光标形成的小孔，不跨越大片不可见区域补造命中区。
        columns = cv2.morphologyEx(
            columns.astype(np.uint8)[None, :], cv2.MORPH_CLOSE, np.ones((1, 3), np.uint8)
        )[0].astype(bool)
        spans[name] = tuple((a, b) for a, b in _spans(columns) if b - a >= 3)
        if name in ("red", "purple"):
            # 数字与球体描边不等于牙齿/毒浪；跨出球体的叠加障碍仍保留。
            spans[name] = tuple(
                (a, b)
                for a, b in spans[name]
                if not any(left <= a and b <= right for left, right in bubbles)
            )
    blocked = np.zeros(width, bool)
    for left, right in spans["purple"] + spans["red"]:
        blocked[max(0, left - margin) : min(width, right + margin)] = True
    green_present = cv2.countNonZero(masks["green"]) >= max(8, round(height * width * 0.003))
    green = None
    if len(spans["green"]) == 1:
        left, right = spans["green"][0]
        if right - left >= max(8, height):
            # 当前真实样本明暗有多段纹理；未确认起始端时不从几何左边缘猜测 keyDown。
            green = GreenTarget(left, right)
    return MechanismRegions(green_present, green, blocked, spans["purple"], spans["red"], bubbles)
