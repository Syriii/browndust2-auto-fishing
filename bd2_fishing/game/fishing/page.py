"""钓鱼待机页的只读确认，不从空白画面或 QTE 消失推断可操作。"""

import cv2
import numpy as np

from bd2_fishing.game.fishing.templates import best_score as _best_score
from bd2_fishing.game.fishing.templates import load_pattern as _load_pattern
from bd2_fishing.perception import image as vision
from bd2_fishing.runtime.geometry import Rect, scale_pixel_threshold


class FishingPageReader:
    """区分有方向键的待机与水花按钮等待状态，只在流程衔接使用。"""

    CAST_BOUNDS = (803, 391, 909, 513)
    ARROW_CENTERS = {"up": (142, 402), "left": (110, 435), "right": (175, 435), "down": (142, 467)}

    COMPACT_BOUNDS = {"splash": (812, 405, 895, 485), "space": (843, 498, 872, 512)}

    def __init__(self, window, config=None):
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
        self.compact_patterns = {}
        self.time_region = None
        if config is not None:
            for name, (left, top, right, bottom) in self.COMPACT_BOUNDS.items():
                patterns = self._scale_patterns(
                    _load_pattern(f"idle_{name}"), right - left, bottom - top
                )
                self.compact_patterns[name] = [(p >= 215).astype(np.uint8) * 255 for p in patterns]
            local = Rect(0, 0, window.width, window.height)
            control = vision.build_region_from_config(config, "roi", local)
            self.time_region = vision.build_region_from_config(
                config, "roi", control, prefix="time"
            )
            self.time_ranges = [
                vision.read_hsv_range_from_keys(
                    config,
                    "roi",
                    lower_prefix=f"time_lower_{color}",
                    upper_prefix=f"time_upper_{color}",
                )
                for color in ("green", "red")
            ]
            self.time_threshold = scale_pixel_threshold(
                50, vision.build_pixel_threshold_scale(config, window)
            )

    def _scale_patterns(self, raw, reference_width, reference_height):
        width = max(2, round(reference_width * self.window.width / 945))
        height = max(2, round(reference_height * self.window.height / 532))
        return [
            cv2.resize(raw, (max(2, width + dx), max(2, height + dy)))
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
        ]

    def _crop(self, frame, bounds, margin=3):
        left, top, right, bottom = bounds
        roi = frame[
            max(0, round(top * self.window.height / 532) - margin) : min(
                self.window.height, round(bottom * self.window.height / 532) + margin
            ),
            max(0, round(left * self.window.width / 945) - margin) : min(
                self.window.width, round(right * self.window.width / 945) + margin
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

    def inspect_waiting(self, frame, idle_scores=None):
        """水花与 SPACE 同时可见、无方向键及计时条，才是等待候选。"""
        scores = {}
        if (
            self.time_region is None
            or frame is None
            or frame.shape[:2] != (self.window.height, self.window.width)
        ):
            return False, scores
        if idle_scores is None:
            _, idle_scores = self.inspect(frame)
        if any(idle_scores[f"movement_{name}"] >= 0.88 for name in self.ARROW_CENTERS):
            return False, scores
        # 只扩大局部查找范围以容纳用户截屏边缘偏差，字形门槛仍为 0.88。
        margin = max(3, round(16 * self.window.width / 945))
        for name, bounds in self.COMPACT_BOUNDS.items():
            white = (self._crop(frame, bounds, margin) >= 215).astype(np.uint8) * 255
            scores[f"compact_{name}"] = _best_score(white, self.compact_patterns[name])
        compact = all(scores[f"compact_{name}"] >= 0.88 for name in self.COMPACT_BOUNDS)
        if not compact:
            return False, scores
        rect = self.time_region
        timer = cv2.cvtColor(
            frame[rect.top : rect.bottom, rect.left : rect.right], cv2.COLOR_BGR2HSV
        )
        pixels = sum(
            cv2.countNonZero(cv2.inRange(timer, color.lower, color.upper))
            for color in self.time_ranges
        )
        scores["compact_qte_absent"] = float(pixels <= self.time_threshold)
        return pixels <= self.time_threshold, scores
