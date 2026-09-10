"""钓鱼待机页的只读确认，不从空白画面或 QTE 消失推断可操作。"""

from pathlib import Path

import cv2
import numpy as np


def _load_pattern(name):
    raw = cv2.imdecode(
        np.frombuffer((Path(__file__).with_name("assets") / f"{name}.png").read_bytes(), np.uint8),
        cv2.IMREAD_GRAYSCALE,
    )
    if raw is None or raw.std() < 1:
        raise ValueError("钓鱼待机模板无有效图形")
    return raw


def _best_score(gray, patterns):
    best = 0.0
    for pattern in patterns:
        if pattern.std() < 1 or any(a < b for a, b in zip(gray.shape, pattern.shape)):
            continue
        match = cv2.matchTemplate(gray, pattern, cv2.TM_CCOEFF_NORMED)
        finite = match[np.isfinite(match)]
        if finite.size:
            best = max(best, float(finite.max()))
    return best


class FishingPageReader:
    """四个方向箭头和抛竿控件同时确认；只在结算/续钓阶段使用。"""

    CAST_BOUNDS = (803, 391, 909, 513)
    ARROW_CENTERS = {"up": (142, 402), "left": (110, 435), "right": (175, 435), "down": (142, 467)}

    def __init__(self, window):
        self.window = window
        self.cast_patterns = []
        for variant in ("", "_night_945", "_night_875", "_day_875", "_day_945"):
            self.cast_patterns.extend(
                self._scale_patterns(_load_pattern(f"idle_cast{variant}"), 106, 122)
            )
        movement = _load_pattern("idle_movement")
        self.arrows = {}
        for name, (x, y) in self.ARROW_CENTERS.items():
            # 只比较箭头字形，不把透明按钮的背景当作模板内容。
            crop = movement[y - 390 - 5 : y - 390 + 6, x - 98 - 5 : x - 98 + 6]
            gray = self._scale_patterns(crop, 11, 11)
            white = [(pattern >= 215).astype(np.uint8) * 255 for pattern in gray]
            self.arrows[name] = (gray, white)

    def _scale_patterns(self, raw, reference_width, reference_height):
        width = max(2, round(reference_width * self.window.width / 945))
        height = max(2, round(reference_height * self.window.height / 532))
        return [
            cv2.resize(raw, (max(2, width + dx), max(2, height + dy)))
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
        ]

    def _crop(self, frame, bounds):
        left, top, right, bottom = bounds
        roi = frame[
            max(0, round(top * self.window.height / 532) - 3) : min(
                self.window.height, round(bottom * self.window.height / 532) + 3
            ),
            max(0, round(left * self.window.width / 945) - 3) : min(
                self.window.width, round(right * self.window.width / 945) + 3
            ),
        ]
        return cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    def inspect(self, frame):
        scores = {}
        if frame is None or frame.shape[:2] != (self.window.height, self.window.width):
            return False, scores
        for name, (x, y) in self.ARROW_CENTERS.items():
            gray = self._crop(frame, (x - 5, y - 5, x + 6, y + 6))
            white = (gray >= 215).astype(np.uint8) * 255
            gray_patterns, white_patterns = self.arrows[name]
            scores[f"movement_{name}"] = max(
                _best_score(gray, gray_patterns), _best_score(white, white_patterns)
            )
        scores["idle_movement"] = min(scores.values())
        scores["idle_cast"] = _best_score(self._crop(frame, self.CAST_BOUNDS), self.cast_patterns)
        return all(score >= 0.88 for score in scores.values()), scores
