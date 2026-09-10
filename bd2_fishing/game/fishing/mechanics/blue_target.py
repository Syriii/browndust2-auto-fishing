"""蓝区的可按内部边界；不将颜色膨胀或光标容差作为命中许可。"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BlueTarget:
    visible_spans: tuple[tuple[int, int], ...]
    safe_spans: tuple[tuple[int, int], ...]
    overlap: bool | None
    repaired_cursor_gap: tuple[int, int] | None = None


def _spans(columns):
    changes = np.diff(np.r_[False, columns, False].astype(np.int8))
    return tuple(zip(np.flatnonzero(changes == 1).tolist(), np.flatnonzero(changes == -1).tolist()))


def read_blue_target(mask, cursor, *, blocked=None, active_range=None):
    """只修补可信光标盖住的窄孔；端点不外扩，障碍和宽缺口不填平。"""
    height, width = mask.shape
    if height < 5 or width < 3:
        return BlueTarget((), (), None)
    trim = max(1, height // 10)
    body = mask[trim:-trim]
    # 去除上下描边与零星蓝光：每列至少有足够高度的实体蓝色。
    columns = np.count_nonzero(body, axis=0) >= max(2, body.shape[0] * 0.35)
    allowed = np.ones(width, dtype=bool)
    if blocked is not None:
        allowed &= ~blocked
    if active_range is not None:
        left, right = active_range
        allowed[: max(0, left)] = False
        allowed[max(0, right + 1) :] = False
    columns &= allowed
    visible = _spans(columns)
    repaired = None
    if cursor is not None and 0 <= cursor < width and allowed[cursor]:
        # 蓝色两侧真实存在、缺口恰好包含当前真光标时才能修补。
        # 19px 高的真实 ROI 中，光标及光晕会盖住 8–9 列蓝色。
        max_gap = max(3, round(height * 0.5))
        support_width = max(2, round(height * 0.15))
        for (start, left), (right, end) in zip(visible, visible[1:]):
            if (
                left <= cursor < right
                and right - left <= max_gap
                and left - start >= support_width
                and end - right >= support_width
                and allowed[left:right].all()
            ):
                columns[left:right] = True
                repaired = (left, right)
                break
    inset = max(1, round(height * 0.06))
    minimum_width = max(3, round(height * 0.25))
    safe = tuple(
        (left + inset, right - inset)
        for left, right in _spans(columns)
        if right - left >= max(minimum_width, inset * 2 + 1)
    )
    overlap = None
    if safe and cursor is not None and 0 <= cursor < width and allowed[cursor]:
        if any(left <= cursor < right for left, right in safe):
            overlap = True
        elif any(left <= cursor < right for left, right in _spans(columns)):
            # 在安全边距内只能等待，不能因此把同一次重合重新解锁。
            overlap = None
        elif visible and visible[0][0] <= cursor < visible[-1][1]:
            # 区域之间尚未证实的孔洞不能当成已离开目标而重新授权。
            overlap = None
        else:
            overlap = False
    return BlueTarget(visible, safe, overlap, repaired)
