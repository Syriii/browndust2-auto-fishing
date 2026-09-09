"""QTE 光标候选及亮度选择，供控制和独立观察复用。"""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class PointerCandidate:
    x: int
    brightness: float


@dataclass(frozen=True)
class PointerReading:
    x: int | None
    candidates: tuple[PointerCandidate, ...]
    reason: str


def read_pointer(hsv: np.ndarray) -> PointerReading:
    """找窄竖直亮线，再比较候选亮度；色条/亮点不参加排序。"""
    h, w = hsv.shape[:2]
    if h < 5 or w < 9:
        return PointerReading(None, (), "roi_too_small")
    gray = cv2.cvtColor(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR), cv2.COLOR_BGR2GRAY)
    # 去掉上下装饰边缘，用贯穿条体的线段定位，而不是选一粒最亮像素。
    trim = max(1, h // 10)
    values = gray[trim:-trim].astype(np.int16)
    colors = hsv[trim:-trim]
    distance = max(3, round(h * 0.16))
    if w <= distance * 2:
        return PointerReading(None, (), "roi_too_small")
    contrast = np.zeros_like(values)
    contrast[:, distance:-distance] = values[:, distance:-distance] - np.maximum(
        values[:, : -2 * distance], values[:, 2 * distance :]
    )
    # 允许蓝白抗锯齿和浅色分身进入候选；排除黄条、蓝条本身的彩色边缘。
    neutral = (colors[:, :, 1] <= 80) & (colors[:, :, 2] >= 140)
    support = np.count_nonzero((contrast >= 12) & neutral, axis=0) >= values.shape[0] * 0.6
    starts = np.flatnonzero(support & ~np.r_[False, support[:-1]])
    ends = np.flatnonzero(support & ~np.r_[support[1:], False])
    candidates = []
    for left, right in zip(starts, ends):
        if right - left + 1 > distance * 2:
            continue
        scores = np.median(values[:, left : right + 1], axis=0)
        x = int(left + scores.argmax())
        candidates.append(PointerCandidate(x, float(scores.max())))
    candidates.sort(key=lambda candidate: candidate.brightness, reverse=True)
    result = tuple(candidates)
    if not result:
        return PointerReading(None, result, "no_pointer_shape")
    if result[0].brightness < 200:
        return PointerReading(None, result, "only_dim_candidates")
    if len(result) > 1 and result[0].brightness - result[1].brightness < 12:
        return PointerReading(None, result, "ambiguous_brightness")
    return PointerReading(result[0].x, result, "brightest_pointer")
