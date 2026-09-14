"""区分已确认可关闭的结算弹窗；不因标题或特效单独授权点击。"""

import cv2

from bd2_fishing.game.fishing.templates import best_score, load_pattern


class SettlementPanelReader:
    # 固定字形，不使用会变化的等级、属性数字或角色/海面背景。
    LEVEL_BOUNDS = {"title": (426, 87, 518, 108), "labels": (350, 123, 409, 195)}
    LABEL_BOUNDS = ((366, 124, 409, 136), (366, 152, 390, 164), (366, 180, 390, 192))

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
        for name, bounds in self.LEVEL_BOUNDS.items():
            raw = [load_pattern(f"level_up_{name}"), load_pattern(f"level_up_{name}_day")]
            if name == "title":
                raw.append(load_pattern("level_up_title_night"))
            self.regions[name] = self._scaled_region(bounds, raw)
        # 透明面板后的海面和天空会变化；只比较三行固定文字，不包含行间背景。
        labels = [
            cv2.resize(load_pattern(name), (59, 72))
            for name in ("level_up_labels", "level_up_labels_day", "level_up_labels_night")
        ]
        self.label_regions = []
        for bounds in self.LABEL_BOUNDS:
            left, top, right, bottom = bounds
            self.label_regions.append(
                self._scaled_region(
                    bounds,
                    [raw[top - 123 : bottom - 123, left - 350 : right - 350] for raw in labels],
                )
            )

    def _scaled_region(self, bounds, raw_patterns):
        left, top, right, bottom = bounds
        window = self.window
        width = max(2, round((right - left) * window.width / 945))
        height = max(2, round((bottom - top) * window.height / 532))
        patterns = [
            cv2.resize(raw, (max(2, width + dx), max(2, height + dy)))
            for raw in raw_patterns
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
        ]
        search = (
            max(0, round(left * window.width / 945) - 3),
            max(0, round(top * window.height / 532) - 3),
            min(window.width, round(right * window.width / 945) + 3),
            min(window.height, round(bottom * window.height / 532) + 3),
        )
        return search, patterns

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
        if scores["title"] >= 0.88 and scores["labels"] < 0.88:
            label_scores = [
                best_score(
                    cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY), patterns
                )
                for (left, top, right, bottom), patterns in self.label_regions
            ]
            scores["labels"] = max(scores["labels"], min(label_scores))
        kind = "level_up" if all(score >= 0.88 for score in scores.values()) else "result"
        return kind, scores
