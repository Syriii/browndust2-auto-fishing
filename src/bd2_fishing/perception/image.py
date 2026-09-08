"""通用 HSV 遮罩、区域配置与像素缩放；不包含钓鱼判定。"""

from __future__ import annotations

import configparser
import logging
from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np

from bd2_fishing.runtime.geometry import PixelThresholdScale, Rect, build_region_from_percent

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HSVRange:
    """OpenCV HSV 颜色范围的上下界。"""

    lower: np.ndarray
    upper: np.ndarray


def read_hsv_range(config: configparser.ConfigParser, section: str, prefix: str) -> HSVRange:
    """按 ``<prefix>_lower/upper_*`` 命名约定读取 HSV 范围。"""
    return read_hsv_range_from_keys(
        config,
        section,
        lower_prefix=f"{prefix}_lower",
        upper_prefix=f"{prefix}_upper",
    )


def read_hsv_range_from_keys(
    config: configparser.ConfigParser,
    section: str,
    *,
    lower_prefix: str,
    upper_prefix: str,
) -> HSVRange:
    """使用分别指定的上下界前缀读取 HSV 范围。"""
    lower = np.array(
        [
            config.getint(section, f"{lower_prefix}_hue"),
            config.getint(section, f"{lower_prefix}_saturation"),
            config.getint(section, f"{lower_prefix}_value"),
        ]
    )
    upper = np.array(
        [
            config.getint(section, f"{upper_prefix}_hue"),
            config.getint(section, f"{upper_prefix}_saturation"),
            config.getint(section, f"{upper_prefix}_value"),
        ]
    )
    return HSVRange(lower=lower, upper=upper)


def build_pixel_threshold_scale(
    config: configparser.ConfigParser,
    region: Rect,
) -> PixelThresholdScale:
    """根据游戏窗口和配置中的参考分辨率创建阈值缩放信息。"""
    reference_width = config.getint("scale", "reference_window_width", fallback=3840)
    reference_height = config.getint("scale", "reference_window_height", fallback=2160)
    return PixelThresholdScale(
        reference_width=reference_width,
        reference_height=reference_height,
        current_width=region.width,
        current_height=region.height,
    )


def build_region_from_config(
    config: configparser.ConfigParser,
    section: str,
    window_region: Rect,
    *,
    prefix: str = "",
) -> Rect:
    """从配置节读取百分比区域；可用前缀区分同节中的多个区域。"""
    key_prefix = f"{prefix}_" if prefix else ""
    return build_region_from_percent(
        window_region,
        left_percent=config.getint(section, f"{key_prefix}left_percent"),
        top_percent=config.getint(section, f"{key_prefix}top_percent"),
        right_percent=config.getint(section, f"{key_prefix}right_percent"),
        bottom_percent=config.getint(section, f"{key_prefix}bottom_percent"),
    )


def create_color_mask(
    lower_color: Iterable[int] | np.ndarray,
    upper_color: Iterable[int] | np.ndarray,
    roi_hsv: np.ndarray,
    *,
    is_dilate: bool = True,
    dilate_kernel_size: tuple[int, int] = (7, 7),
    dilate_iterations: int = 2,
) -> np.ndarray:
    """创建 HSV 二值遮罩，并按需膨胀以连接断裂或被遮挡的颜色区域。"""
    lower = np.array(lower_color)
    upper = np.array(upper_color)
    mask = cv2.inRange(roi_hsv, lower, upper)
    if is_dilate:
        # NumPy 核尺寸顺序为（高度, 宽度），迭代次数越多扩张范围越大。
        kernel = np.ones(dilate_kernel_size, np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=dilate_iterations)
    return mask
