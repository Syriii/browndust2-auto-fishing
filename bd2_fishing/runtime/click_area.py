"""在调用方确认的有效矩形内选择落点；不识别页面、不执行输入。"""

import math
import random

from bd2_fishing.runtime.geometry import Rect


def random_point(bounds: Rect, *, inset_ratio: float = 0.2) -> tuple[int, int]:
    """从内缩后的整数像素均匀采样；矩形右、下边界不包含在有效区域内。"""
    if any(type(value) is not int for value in bounds.as_tuple()):
        raise ValueError("点击区域必须使用整数像素坐标")
    if bounds.width <= 0 or bounds.height <= 0:
        raise ValueError("点击区域必须有正宽高")
    if not math.isfinite(inset_ratio) or not 0 <= inset_ratio < 0.5:
        raise ValueError("点击内缩比例必须为 0 到 0.5 之间（不含 0.5）")
    inset_x = min((bounds.width - 1) // 2, math.ceil(bounds.width * inset_ratio))
    inset_y = min((bounds.height - 1) // 2, math.ceil(bounds.height * inset_ratio))
    return (
        random.randint(bounds.left + inset_x, bounds.right - inset_x - 1),
        random.randint(bounds.top + inset_y, bounds.bottom - inset_y - 1),
    )
