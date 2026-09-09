"""钓鱼亮字反馈识别，不创建线程或设备；灰字结算提示使用独立模板。"""

from pathlib import Path

import cv2
import numpy as np


def white_text(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 185), (180, 105, 255))
    return cv2.GaussianBlur(mask, (3, 3), 0.8)


def vertical_text_edges(frame):
    """文字的纵向亮度梯度；削弱贯穿画面的竖向光柱影响。"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)


class FeedbackMatcher:
    """仅匹配实测反馈字形；不以按键位置或进度变化推测命中。"""

    def __init__(self, width, height, assets=None):
        assets = Path(assets or Path(__file__).with_name("assets"))
        self.patterns = {}
        self.critical_edges = []
        templates = [
            (name, 875, 492) for name in ("critical", "critical_alt", "hit", "miss", "fail")
        ]
        templates.extend([("hit_effect_945", 945, 532), ("hit_plain_945", 945, 532)])
        for name, reference_width, reference_height in templates:
            image = cv2.imdecode(np.frombuffer((assets / f"{name}.png").read_bytes(), np.uint8), 1)
            if image is None:
                raise ValueError(f"反馈模板无法解码: {name}")
            # 按每张原图的客户区缩放；匹配位置不固定，保留反馈动画的字形变体。
            image = cv2.resize(
                image,
                (
                    max(1, round(image.shape[1] * width / reference_width)),
                    max(1, round(image.shape[0] * height / reference_height)),
                ),
            )
            self.patterns.setdefault(name.split("_")[0], []).append(white_text(image))
            if name in ("critical", "critical_alt"):
                # 仅补暴击长字形，采用旧模板而非把待测强光图制作成模板。
                for delta in (-1, 0, 1):
                    resized = cv2.resize(image, (image.shape[1], max(5, image.shape[0] + delta)))
                    if min(resized.shape[:2]) <= 4:
                        continue
                    self.critical_edges.append(
                        (
                            vertical_text_edges(resized)[2:-2, 2:-2],
                            cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)[2:-2, 2:-2],
                        )
                    )

    def _critical_under_glare(self, frame):
        edges = vertical_text_edges(frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        best = 0.0
        for pattern, gray_pattern in self.critical_edges:
            h, w = pattern.shape
            if edges.shape[0] < h or edges.shape[1] < w:
                continue
            _, score, _, (x, y) = cv2.minMaxLoc(
                cv2.matchTemplate(edges, pattern, cv2.TM_CCOEFF_NORMED)
            )
            if score < 0.80:
                continue
            # 相同位置还必须符合完整灰度字形，不能只凭一组相似边缘认作暴击。
            gray_score = float(
                cv2.matchTemplate(gray[y : y + h, x : x + w], gray_pattern, cv2.TM_CCOEFF_NORMED)[
                    0, 0
                ]
            )
            if gray_score >= 0.65:
                best = max(best, score)
        return best

    def detect(self, frame):
        mask = white_text(frame)
        scores = []
        for name, patterns in self.patterns.items():
            group = []
            for pattern in patterns:
                if mask.shape[0] >= pattern.shape[0] and mask.shape[1] >= pattern.shape[1]:
                    group.append(
                        float(
                            cv2.minMaxLoc(cv2.matchTemplate(mask, pattern, cv2.TM_CCOEFF_NORMED))[1]
                        )
                    )
            if group:
                scores.append((max(group), name))
        scores.sort(reverse=True)
        if not scores or scores[0][0] < 0.80:
            edge_score = self._critical_under_glare(frame)
            if edge_score:
                return "critical", edge_score
            return None, scores[0][0] if scores else 0.0
        if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.12:
            return None, scores[0][0]
        return scores[0][1], scores[0][0]
