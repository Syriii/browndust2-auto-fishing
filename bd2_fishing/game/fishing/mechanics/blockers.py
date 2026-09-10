"""深渊挡板的同帧纯识别；保留既有单挡板规则，不代表多墙/贝壳已支持。"""

import cv2
import numpy as np

from bd2_fishing.perception import image as vision


class BlockerDetector:
    def __init__(self, ranges, *, min_width, max_width, min_height, max_height):
        self.ranges = tuple(ranges)
        self.min_width, self.max_width = min_width, max_width
        self.min_height, self.max_height = min_height, max_height

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

    def read(
        self,
        qte_hsv: np.ndarray,
        cursor_mask: np.ndarray,
    ) -> tuple[int, int, int, int] | None:
        """先排除高亮光标，再从修补后的挡板遮罩中寻找候选矩形。"""
        kernel = np.ones((3, 3), np.uint8)
        # 轻微扩张可覆盖光标抗锯齿边缘，避免残留白边被识别成挡板。
        cursor_mask_for_overlap = cv2.dilate(cursor_mask, kernel, iterations=1)

        without_cursor_mask = qte_hsv.copy()
        # HSV 的零值代表黑色，不会落入当前挡板的高亮颜色范围。
        without_cursor_mask[cursor_mask_for_overlap > 0] = [0, 0, 0]
        blocker_mask = self._filtered_blocker_mask(self._blocker_mask(without_cursor_mask))
        blocker_rect = self._find_blocker(blocker_mask)
        return blocker_rect

    def _filtered_blocker_mask(self, blocker_mask: np.ndarray) -> np.ndarray:
        """用闭运算填补挡板内部孔洞，同时尽量保持外轮廓尺寸。"""
        # 核高大于核宽，更适合修补瘦高挡板纵向上的断裂。
        kernel = np.ones((6, 4), np.uint8)
        filtered_mask = cv2.morphologyEx(blocker_mask, cv2.MORPH_CLOSE, kernel)
        return filtered_mask

    def _find_blocker(self, closed_mask: np.ndarray) -> tuple[int, int, int, int] | None:
        """按轮廓宽高和长宽比筛选挡板，并返回首个匹配边界框。"""
        contours, _ = cv2.findContours(closed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)

            # 挡板应为瘦高矩形：宽高范围读取配置，比例用于排除形状相近的干扰。
            aspect_ratio = float(h) / w

            if (
                self.min_width < w < self.max_width
                and self.min_height < h < self.max_height
                and 2.0 < aspect_ratio < 7.0
            ):
                return x, y, w, h

        return None


def active_range_for_blocker(
    blocker_rect: tuple[int, int, int, int] | None,
    cursor_x: int,
    mask_width: int,
) -> tuple[int, int]:
    """将挡板矩形当作边界，只保留光标当前能够活动的一侧。"""
    if blocker_rect is None:
        return 0, mask_width - 1

    x, _y, w, _h = blocker_rect
    blocker_left = max(0, x)
    blocker_right = min(mask_width - 1, x + w - 1)

    # 挡板在光标右边：只看最左边到挡板左侧
    if cursor_x < blocker_left:
        return 0, max(0, blocker_left - 1)

    # 挡板在光标左边：只看挡板右侧到最右边
    if cursor_x > blocker_right:
        return min(mask_width - 1, blocker_right + 1), mask_width - 1

    # 光标刚好落在挡板矩形内，兜底：按离哪边近来切
    blocker_center = (blocker_left + blocker_right) // 2
    if cursor_x <= blocker_center:
        return 0, max(0, blocker_left - 1)
    return min(mask_width - 1, blocker_right + 1), mask_width - 1
