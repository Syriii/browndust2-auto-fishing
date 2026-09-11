"""导航确认框的快速识别；动作由导航处理，不能当作鱼获结算关闭。"""

import cv2

from bd2_fishing.game.fishing.templates import best_score, load_pattern


class FishingDialogReader:
    REGIONS = {
        "stamina_error": {
            "stamina_error_text": (390, 246, 556, 264),
            "stamina_error_confirm": (458, 282, 489, 301),
        },
        "return_to_dock": {
            "return_dock_title": (440, 188, 511, 212),
            "return_dock_question": (395, 232, 551, 250),
        },
        "travel_confirmation": {
            "travel_title": (420, 192, 534, 215),
            "travel_warning": (340, 254, 605, 272),
        },
    }

    def __init__(self):
        self.patterns = {}
        for regions in self.REGIONS.values():
            for name in regions:
                pattern = load_pattern(name)
                self.patterns[name] = [
                    cv2.resize(pattern, None, fx=s, fy=s) for s in (0.98, 1, 1.02)
                ]

    def inspect(self, frame):
        normalized = cv2.resize(frame, (945, 532), interpolation=cv2.INTER_AREA)
        scores = {}
        for kind, regions in self.REGIONS.items():
            matched = []
            for name, (left, top, right, bottom) in regions.items():
                gray = cv2.cvtColor(
                    normalized[top - 10 : bottom + 10, left - 10 : right + 10], cv2.COLOR_BGR2GRAY
                )
                scores[name] = best_score(gray, self.patterns[name])
                matched.append(scores[name] >= 0.88)
            if all(matched):
                return kind, scores
        return None, scores
