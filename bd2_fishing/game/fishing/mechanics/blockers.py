"""挡板同帧纯识别与多墙可达区间；不将挡板当作贝壳。"""

import cv2
import numpy as np

from bd2_fishing.perception import image as vision
from bd2_fishing.runtime import geometry


class BlockerDetector:
    MIN_SOURCE_FILL = 0.5

    def __init__(self, ranges, *, min_width, max_width, min_height, max_height):
        self.ranges = tuple(ranges)
        self.min_width, self.max_width = min_width, max_width
        self.min_height, self.max_height = min_height, max_height

    @classmethod
    def from_config(cls, config, scale):
        """控制和独立观察使用同一配置缩放，实例不持有跨帧状态。"""
        bounds = {}
        for dimension, factor, low, high in (
            ("width", scale.width_factor, 4, 20),
            ("height", scale.height_factor, 18, 100),
        ):
            minimum = geometry.scale_pixel_length(
                config.getint("roi", f"blocker_shape_min_{dimension}", fallback=low), factor
            )
            maximum = geometry.scale_pixel_length(
                config.getint("roi", f"blocker_shape_max_{dimension}", fallback=high), factor
            )
            bounds[f"min_{dimension}"] = minimum
            bounds[f"max_{dimension}"] = max(minimum + 1, maximum)
        ranges = [
            vision.read_hsv_range(config, "roi", name) for name in ("blocker_one", "blocker_two")
        ]
        return cls(ranges, **bounds)

    def parameters(self):
        return dict(
            ranges=[
                dict(lower=value.lower.tolist(), upper=value.upper.tolist())
                for value in self.ranges
            ],
            min_width=self.min_width,
            max_width=self.max_width,
            min_height=self.min_height,
            max_height=self.max_height,
            minimum_source_fill=self.MIN_SOURCE_FILL,
        )

    def _blocker_mask(self, qte_hsv: np.ndarray) -> np.ndarray:
        """合并挡板在不同画面亮度下的多个 HSV 颜色区间。"""
        blocker_mask = vision.create_color_mask(
            self.ranges[0].lower,
            self.ranges[0].upper,
            qte_hsv,
            is_dilate=False,
        )
        for blocker_range in self.ranges[1:]:
            range_mask = vision.create_color_mask(
                blocker_range.lower,
                blocker_range.upper,
                qte_hsv,
                is_dilate=False,
            )
            blocker_mask = cv2.bitwise_or(blocker_mask, range_mask)
        return blocker_mask

    def read_all(self, qte_hsv, cursor_mask) -> tuple[tuple[int, int, int, int], ...]:
        """先排除高亮光标，再从修补后的挡板遮罩中寻找候选矩形。"""
        kernel = np.ones((3, 3), np.uint8)
        # 轻微扩张可覆盖光标抗锯齿边缘，避免残留白边被识别成挡板。
        cursor_mask_for_overlap = cv2.dilate(cursor_mask, kernel, iterations=1)

        without_cursor_mask = qte_hsv.copy()
        # HSV 的零值代表黑色，不会落入当前挡板的高亮颜色范围。
        without_cursor_mask[cursor_mask_for_overlap > 0] = [0, 0, 0]
        source_mask = self._blocker_mask(without_cursor_mask)
        blocker_mask = self._filtered_blocker_mask(source_mask)
        return self._find_blockers(blocker_mask, source_mask)

    def _filtered_blocker_mask(self, blocker_mask: np.ndarray) -> np.ndarray:
        """用闭运算填补挡板内部孔洞，同时尽量保持外轮廓尺寸。"""
        # 核高大于核宽，更适合修补瘦高挡板纵向上的断裂。
        kernel = np.ones((6, 4), np.uint8)
        filtered_mask = cv2.morphologyEx(blocker_mask, cv2.MORPH_CLOSE, kernel)
        return filtered_mask

    def _find_blockers(
        self, closed_mask: np.ndarray, source_mask: np.ndarray
    ) -> tuple[tuple[int, int, int, int], ...]:
        """保留同帧全部候选，按位置排序，不依赖 OpenCV 轮廓枚举顺序。"""
        contours, _ = cv2.findContours(closed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        found = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)

            # 挡板应为瘦高矩形：宽高范围读取配置，比例用于排除形状相近的干扰。
            aspect_ratio = float(h) / w

            if (
                self.min_width < w < self.max_width
                and self.min_height < h < self.max_height
                and 2.0 < aspect_ratio < 7.0
                # 闭运算只能修补实体，不能将光标边缘或黄条纹理补成整面墙。
                and cv2.countNonZero(source_mask[y : y + h, x : x + w])
                >= w * h * self.MIN_SOURCE_FILL
            ):
                found.append((x, y, w, h))

        return tuple(sorted(found))


def active_range_for_blockers(blockers, cursor_x, mask_width) -> tuple[int, int] | None:
    """取所有墙约束的交集；光标在墙内时无可达区间，禁止投影到墙外。"""
    if cursor_x is None or not 0 <= cursor_x < mask_width:
        return None
    left, right = 0, mask_width - 1
    for x, _y, width, _height in blockers:
        if width <= 0 or x + width <= 0 or x >= mask_width:
            continue
        a, b = max(0, x), min(mask_width - 1, x + width - 1)
        if a <= cursor_x <= b:
            return None
        if cursor_x < a:
            right = min(right, a - 1)
        else:
            left = max(left, b + 1)
    return (left, right) if left <= cursor_x <= right else None
