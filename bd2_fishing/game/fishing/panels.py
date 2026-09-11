"""区分已确认可关闭的结算弹窗；不因标题或特效单独授权点击。"""

import cv2

from bd2_fishing.game.fishing.templates import best_score, load_pattern


class SettlementPanelReader:
    # 固定字形，不使用会变化的等级、属性数字或角色/海面背景。
    LEVEL_BOUNDS = {"title": (426, 87, 518, 108), "labels": (350, 123, 409, 195)}

    def __init__(self, window):
        self.window = window
        self.close_patterns = []
        for name, reference_width, reference_height in (
            ("settlement_close", 875, 492),
            ("settlement_close_945", 945, 532),
        ):
            raw = load_pattern(name)
            width = round(raw.shape[1] * window.width / reference_width)
            height = round(raw.shape[0] * window.height / reference_height)
            self.close_patterns.extend(
                cv2.resize(raw, (max(2, width + dx), max(2, height + dy)))
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
            )
        self.regions = {}
        for name, (left, top, right, bottom) in self.LEVEL_BOUNDS.items():
            raw = load_pattern(f"level_up_{name}")
            width = max(2, round((right - left) * window.width / 945))
            height = max(2, round((bottom - top) * window.height / 532))
            patterns = [
                cv2.resize(raw, (max(2, width + dx), max(2, height + dy)))
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
            ]
            bounds = (
                max(0, round(left * window.width / 945) - 3),
                max(0, round(top * window.height / 532) - 3),
                min(window.width, round(right * window.width / 945) + 3),
                min(window.height, round(bottom * window.height / 532) + 3),
            )
            self.regions[name] = (bounds, patterns)

    def is_open(self, frame):
        """关闭提示只证明存在可关闭面板，不能单独证明获得鱼奖励。"""
        if frame is None or frame.shape[:2] != (self.window.height, self.window.width):
            return False
        roi = frame[
            round(self.window.height * 0.88) : round(self.window.height * 0.97),
            round(self.window.width * 0.40) : round(self.window.width * 0.60),
        ]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        return best_score(gray, self.close_patterns) >= 0.85

    def inspect(self, frame, *, close_visible):
        if (
            not close_visible
            or frame is None
            or frame.shape[:2] != (self.window.height, self.window.width)
        ):
            return None, {}
        scores = {}
        for name, ((left, top, right, bottom), patterns) in self.regions.items():
            gray = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
            scores[name] = best_score(gray, patterns)
        kind = "level_up" if all(score >= 0.88 for score in scores.values()) else "result"
        return kind, scores
