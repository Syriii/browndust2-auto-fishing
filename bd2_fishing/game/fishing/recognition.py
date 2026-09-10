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


def warm_text(frame):
    """暴击橙色描边的红蓝差值，削弱白色和蓝色光柱；不用于推断命中区域。"""
    return np.maximum(frame[:, :, 2].astype(np.float32) - frame[:, :, 0], 0)


class FeedbackMatcher:
    """仅匹配实测反馈字形；不以按键位置或进度变化推测命中。"""

    def __init__(self, width, height, assets=None):
        assets = Path(assets or Path(__file__).with_name("assets"))
        self.patterns = {}
        self.critical_edges = []
        self.hit_edges = []
        self.critical_warm = []
        self._last_frame = None
        self._last_result = None
        self.last_method = None
        self.cache_hit = False
        templates = [
            (name, 875, 492) for name in ("critical", "critical_alt", "hit", "miss", "fail")
        ]
        templates.extend(
            [
                ("hit_effect_945", 945, 532),
                ("hit_plain_945", 945, 532),
                ("hit_compact_945", 945, 532),
                ("critical_plain_945", 945, 532),
            ]
        )
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
            if name in (
                "critical",
                "critical_alt",
                "critical_plain_945",
                "hit_plain_945",
                "hit_compact_945",
            ):
                # 用清晰暴击字形校验强光变化，不从待测强光帧提取模板。
                for delta in (-1, 0, 1):
                    resized = cv2.resize(image, (image.shape[1], max(5, image.shape[0] + delta)))
                    if min(resized.shape[:2]) <= 4:
                        continue
                    edges = self.hit_edges if name.startswith("hit_") else self.critical_edges
                    edges.append(
                        (
                            vertical_text_edges(resized)[2:-2, 2:-2],
                            cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)[2:-2, 2:-2],
                        )
                    )
        # 两个实测动画字形；只为较宽早期字形保留一个 -2px 取整变体。
        # 不遍历任意尺度，也不把被遮挡文字截成半个词来匹配。
        for name, offsets in (("critical_plain_945", (0,)), ("critical_early_945", (0, -2))):
            raw = cv2.imdecode(np.frombuffer((assets / f"{name}.png").read_bytes(), np.uint8), 1)
            if raw is None:
                raise ValueError(f"反馈模板无法解码: {name}")
            for offset in offsets:
                image = cv2.resize(
                    raw,
                    (
                        max(5, round((raw.shape[1] + offset) * width / 945)),
                        max(5, round(raw.shape[0] * height / 532)),
                    ),
                )[2:-2, 2:-2]
                color = warm_text(image)
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                if color.std() >= 1 and gray.std() >= 1:
                    self.critical_warm.append((color, gray))

    def _critical_by_color(self, frame):
        color = warm_text(frame)
        # 先定位橙色描边；绿色背景、蓝光或单个小提示图标不做整幅模板搜索。
        red_green = frame[:, :, 2].astype(np.float32) - frame[:, :, 1]
        ys, xs = np.nonzero((color >= 60) & (red_green >= 20))
        if not self.critical_warm or len(xs) < 40:
            return 0.0
        if xs.max() - xs.min() + 1 < min(p.shape[1] for p, _ in self.critical_warm) * 0.75:
            return 0.0
        left, top = max(0, int(xs.min()) - 4), max(0, int(ys.min()) - 4)
        right, bottom = int(xs.max()) + 5, int(ys.max()) + 5
        color = color[top:bottom, left:right]
        frame = frame[top:bottom, left:right]
        gray = None
        for pattern, gray_pattern in self.critical_warm:
            h, w = pattern.shape
            if color.shape[0] < h or color.shape[1] < w:
                continue
            _, score, _, (x, y) = cv2.minMaxLoc(
                cv2.matchTemplate(color, pattern, cv2.TM_CCOEFF_NORMED)
            )
            if not np.isfinite(score) or score < 0.85:
                continue
            if gray is None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_score = cv2.matchTemplate(
                gray[y : y + h, x : x + w], gray_pattern, cv2.TM_CCOEFF_NORMED
            )[0, 0]
            if np.isfinite(gray_score) and gray_score >= 0.65:
                return score
        return 0.0

    def _critical_under_glare(self, frame):
        return self._word_under_glare(frame, self.critical_edges, 0.80, 0.65)

    def _word_under_glare(self, frame, patterns, edge_threshold, gray_threshold):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
        best = 0.0
        for pattern, gray_pattern in patterns:
            h, w = pattern.shape
            if edges.shape[0] < h or edges.shape[1] < w:
                continue
            _, score, _, (x, y) = cv2.minMaxLoc(
                cv2.matchTemplate(edges, pattern, cv2.TM_CCOEFF_NORMED)
            )
            if not np.isfinite(score) or score < edge_threshold:
                continue
            # 相同位置还必须符合完整灰度字形，不能只凭一组相似边缘认作暴击。
            gray_score = float(
                cv2.matchTemplate(gray[y : y + h, x : x + w], gray_pattern, cv2.TM_CCOEFF_NORMED)[
                    0, 0
                ]
            )
            if np.isfinite(gray_score) and gray_score >= gray_threshold:
                best = max(best, score)
        return best

    def detect(self, frame):
        # GDI 可能连续读到相同游戏帧；只复用逐像素相同的匹配结果，时间由调用方记录。
        self.cache_hit = self._last_frame is not None and np.array_equal(frame, self._last_frame)
        if self.cache_hit:
            return self._last_result
        result = self._detect(frame)
        self._last_frame = frame.copy() if frame.nbytes <= 6 * 1024 * 1024 else None
        self._last_result = result
        return result

    def _detect(self, frame):
        self.last_method = "white_text"
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
            # 补充漏检，不覆盖已有明确文字或类别差值不足的歧义结果。
            color_score = self._critical_by_color(frame)
            if color_score:
                self.last_method = "critical_color"
                return "critical", color_score
            edge_score = self._critical_under_glare(frame)
            if edge_score:
                self.last_method = "critical_edges"
                return "critical", edge_score
            hit_score = self._word_under_glare(frame, self.hit_edges, 0.85, 0.75)
            if hit_score:
                self.last_method = "hit_edges"
                return "hit", hit_score
            self.last_method = "unrecognized"
            return None, scores[0][0] if scores else 0.0
        if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.12:
            self.last_method = "ambiguous"
            return None, scores[0][0]
        return scores[0][1], scores[0][0]
