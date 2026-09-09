"""钓鱼待机页的只读确认，不从空白画面或 QTE 消失推断可操作。"""

from pathlib import Path

import cv2
import numpy as np


class FishingPageReader:
    """同时核对移动控件与抛竿控件；只在结算阶段使用。"""

    ANCHORS = {
        "idle_movement": (98, 390, 187, 482),
        "idle_cast": (803, 391, 909, 513),
    }

    def __init__(self, window):
        self.window = window
        self.patterns = {}
        for name, (left, top, right, bottom) in self.ANCHORS.items():
            width = max(2, round((right - left) * window.width / 945))
            height = max(2, round((bottom - top) * window.height / 532))
            patterns = []
            for variant in ("", "_night_945", "_night_875", "_day_875"):
                raw = cv2.imdecode(
                    np.frombuffer(
                        (Path(__file__).with_name("assets") / f"{name}{variant}.png").read_bytes(),
                        np.uint8,
                    ),
                    cv2.IMREAD_GRAYSCALE,
                )
                if raw is None or raw.std() < 1:
                    raise ValueError("钓鱼待机模板无有效图形")
                patterns.extend(
                    cv2.resize(raw, (max(2, width + dx), max(2, height + dy)))
                    for dx in (-1, 0, 1)
                    for dy in (-1, 0, 1)
                )
            self.patterns[name] = patterns
        # 移动键之间是角色/海面背景，不是控件。只比较四个键，避免动画改变背景导致漏检。
        key_mask = np.zeros((92, 89), np.uint8)
        for left, top, right, bottom in (
            (32, 0, 58, 29),
            (0, 31, 29, 60),
            (61, 31, 89, 60),
            (32, 62, 58, 92),
        ):
            key_mask[top:bottom, left:right] = 255
        self.masks = [
            cv2.resize(key_mask, (p.shape[1], p.shape[0]), interpolation=cv2.INTER_NEAREST)
            for p in self.patterns["idle_movement"]
        ]

    def inspect(self, frame):
        scores = {}
        if frame is None or frame.shape[:2] != (self.window.height, self.window.width):
            return False, scores
        for name, (left, top, right, bottom) in self.ANCHORS.items():
            roi = frame[
                max(0, round(top * self.window.height / 532) - 3) : min(
                    self.window.height, round(bottom * self.window.height / 532) + 3
                ),
                max(0, round(left * self.window.width / 945) - 3) : min(
                    self.window.width, round(right * self.window.width / 945) + 3
                ),
            ]
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            best = 0.0
            for index, pattern in enumerate(self.patterns[name]):
                if pattern.std() < 1 or any(a < b for a, b in zip(gray.shape, pattern.shape)):
                    continue
                match = cv2.matchTemplate(
                    gray,
                    pattern,
                    cv2.TM_CCOEFF_NORMED,
                    mask=self.masks[index] if name == "idle_movement" else None,
                )
                finite = match[np.isfinite(match)]
                if finite.size:
                    best = max(best, float(finite.max()))
            scores[name] = best
        return all(score >= 0.88 for score in scores.values()), scores
