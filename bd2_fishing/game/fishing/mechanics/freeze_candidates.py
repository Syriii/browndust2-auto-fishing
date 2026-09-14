"""冰冻计数外观候选，供后台留证；没有输入授权或破冰控制。"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2


@dataclass(frozen=True)
class FreezeCandidate:
    count: int
    span: tuple[int, int]
    score: float


def _load_digits():
    root = Path(__file__).resolve().parents[1] / "assets"
    digits = tuple(cv2.imread(str(root / f"freeze_digit_{i}.png"), 0) for i in (1, 2, 3))
    if any(digit is None for digit in digits):
        raise RuntimeError("冰冻观察模板缺失，请检查完整程序包")
    return digits


_DIGITS = _load_digits()


@lru_cache(maxsize=8)
def _scaled_digits(height):
    result = []
    for count, digit in enumerate(_DIGITS, 1):
        for ratio in (0.55, 0.65, 0.75, 0.85, 0.95):
            size = round(height * ratio)
            if size < 6:
                continue
            resized = cv2.resize(
                digit, (max(3, round(digit.shape[1] * size / digit.shape[0])), size)
            )
            result.append((count, cv2.GaussianBlur(resized, (3, 3), 0.7)))
    return tuple(result)


def read_freeze_candidate(hsv) -> FreezeCandidate | None:
    """数字形状和周围冰蓝色须同时支持；多数字歧义仍返回未知。"""
    height, width = hsv.shape[:2]
    if height < 12 or width < 12:
        return None
    red = cv2.inRange(hsv, (0, 70, 80), (18, 255, 255)) | cv2.inRange(
        hsv, (165, 70, 80), (180, 255, 255)
    )
    if cv2.countNonZero(red) < max(6, height // 2):
        return None
    cyan = cv2.inRange(hsv, (85, 80, 110), (115, 255, 255))
    if cv2.countNonZero(cyan) < height:
        return None
    red_x, _red_y, red_width, _red_height = cv2.boundingRect(red)
    search_left = max(0, red_x - height)
    search_right = min(width, red_x + red_width + height)
    source = cv2.GaussianBlur(red[:, search_left:search_right], (3, 3), 0.7)
    best = {}
    for count, digit in _scaled_digits(height):
        if digit.shape[1] > source.shape[1]:
            continue
        scores = cv2.matchTemplate(source, digit, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, _y) = cv2.minMaxLoc(scores)
        center = search_left + x + digit.shape[1] // 2
        span = (max(0, center - height // 2), min(width, center + height // 2 + 1))
        # 牙齿倒数同样有红色描边；必须保留计数周边的冰晶颜色依据。
        area = cyan[:, span[0] : span[1]]
        if cv2.countNonZero(area) < area.size * 0.35:
            continue
        candidate = FreezeCandidate(count, span, float(score))
        if count not in best or score > best[count].score:
            best[count] = candidate
    found = sorted(best.values(), key=lambda item: item.score, reverse=True)
    if (
        not found
        or found[0].score < 0.72
        or (len(found) > 1 and found[0].score - found[1].score < 0.08)
    ):
        return None
    return found[0]
