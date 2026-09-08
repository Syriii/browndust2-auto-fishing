"""runtime.geometry：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rect:
    """使用屏幕绝对坐标表示的左闭右开矩形区域。"""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


@dataclass(frozen=True)
class PixelThresholdScale:
    """按当前窗口面积相对参考分辨率缩放像素数量阈值。"""

    reference_width: int
    reference_height: int
    current_width: int
    current_height: int

    @property
    def width_factor(self) -> float:
        """返回当前窗口宽度相对参考窗口宽度的倍率。"""
        return self.current_width / max(1, self.reference_width)

    @property
    def height_factor(self) -> float:
        """返回当前窗口高度相对参考窗口高度的倍率。"""
        return self.current_height / max(1, self.reference_height)

    @property
    def factor(self) -> float:
        """返回当前窗口面积与参考窗口面积之比。"""
        reference_area = max(1, self.reference_width * self.reference_height)
        current_area = max(1, self.current_width * self.current_height)
        return current_area / reference_area


def scale_pixel_threshold(
    base_threshold: int,
    scale: PixelThresholdScale,
    *,
    minimum: int = 1,
) -> int:
    """按窗口面积缩放像素阈值，并保证结果不低于最小值。"""
    return max(minimum, int(round(base_threshold * scale.factor)))


def scale_pixel_length(
    base_length: int,
    factor: float,
    *,
    minimum: int = 0,
) -> int:
    """按单一方向的缩放倍率换算像素长度。"""
    return max(minimum, int(round(base_length * factor)))


def build_region_from_percent(
    window_region: Rect,
    *,
    left_percent: int,
    top_percent: int,
    right_percent: int,
    bottom_percent: int,
) -> Rect:
    """把窗口内百分比区域转换成屏幕绝对坐标。"""
    return Rect(
        left=window_region.left + int(window_region.width * left_percent / 100),
        top=window_region.top + int(window_region.height * top_percent / 100),
        right=window_region.left + int(window_region.width * right_percent / 100),
        bottom=window_region.top + int(window_region.height * bottom_percent / 100),
    )


def build_point_from_ratio(
    window_region: Rect,
    *,
    left_ratio: float,
    top_ratio: float,
) -> tuple[int, int]:
    """把区域内的横纵比例转换成屏幕绝对点击坐标。"""
    return (
        int(window_region.left + window_region.width * left_ratio),
        int(window_region.top + window_region.height * top_ratio),
    )
