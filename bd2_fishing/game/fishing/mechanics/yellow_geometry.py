"""黄条实体分组与短期边界确认；不预测光标、不扩张目标外边界。"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class YellowGeometry:
    span: tuple[int, int] | None
    raw_spans: tuple[tuple[int, int], ...]
    source: str = "current"


def read_yellow_geometry(mask, cursor, forbidden=None):
    height, width = mask.shape
    trim = max(1, height // 10)
    body = mask[trim:-trim]
    if not body.size or not 0 <= cursor < width:
        return YellowGeometry(None, ())
    columns = np.count_nonzero(body, axis=0) >= max(2, body.shape[0] * 0.35)
    edges = np.diff(np.r_[False, columns, False].astype(np.int8))
    spans = tuple(
        (int(a), int(b)) for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))
    )
    if not spans:
        return YellowGeometry(None, ())
    nearest = min(spans, key=lambda span: abs((span[0] + span[1] - 1) / 2 - cursor))
    # 孔内孤立列不是边界：寻找两侧连续实体，跨过光晕内的细碎残色。
    support = max(2, round(height * 0.1))
    left = [s for s in spans if s[1] <= cursor and s[1] - s[0] >= support]
    right = [s for s in spans if s[0] > cursor and s[1] - s[0] >= support]
    if left and right:
        a, b = left[-1], right[0]
        if (
            b[0] - a[1] <= max(3, round(height * 0.95))
            and columns[a[0] : b[1]].sum() >= max(6, round(height * 0.3))
            and (forbidden is None or not forbidden[a[0] : b[1]].any())
        ):
            return YellowGeometry((a[0], b[1]), spans, "cursor_gap")
    return YellowGeometry(nearest, spans)


class YellowTargetMemory:
    """两帧完整边界确认后，最多保留 180ms，且当前两侧仍须有实体颜色。"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.confirmed = None

    def observe(self, reading, cursor, now, shape, forbidden):
        height, _ = shape
        spans = reading.raw_spans
        margin = max(2, round(height * 0.1))
        if self.confirmed is not None:
            span, stamp, old_shape = self.confirmed
            if (
                old_shape != shape
                or not 0 < now - stamp <= 0.18
                or forbidden[span[0] : span[1]].any()
            ):
                self.confirmed = None
        if not spans:
            self.reset()
            return reading
        outer = (spans[0][0], spans[-1][1])
        if self.confirmed is not None:
            span = self.confirmed[0]
            if max(abs(a - b) for a, b in zip(outer, span)) > margin:
                self.confirmed = None
        if len(spans) == 1 and outer[1] - outer[0] >= max(8, round(height * 0.5)):
            clear = not forbidden[outer[0] : outer[1]].any() and (
                cursor < outer[0] - margin or cursor >= outer[1] + margin
            )
            old = self.previous
            self.previous = (outer, now, shape) if clear else None
            if clear and old is not None and old[2] == shape and 0 < now - old[1] <= 0.15:
                if max(abs(a - b) for a, b in zip(outer, old[0])) <= margin:
                    self.confirmed = (outer, now, shape)
        else:
            self.previous = None
        if reading.source == "cursor_gap" or self.confirmed is None:
            return reading
        span = self.confirmed[0]
        left = [s for s in spans if s[1] <= cursor]
        right = [s for s in spans if s[0] > cursor]
        # 单边、全遮挡、宽断口都不能借记忆创建许可；弱边界须与已确认端点一致。
        if (
            left
            and right
            and span[0] + margin <= cursor < span[1] - margin
            and right[0][0] - left[-1][1] <= max(3, round(height * 0.95))
            and sum(b - a for a, b in spans) >= max(6, round(height * 0.3))
            and not forbidden[outer[0] : outer[1]].any()
        ):
            bounded = (max(span[0], outer[0]), min(span[1], outer[1]))
            return YellowGeometry(bounded, spans, "confirmed_edges")
        return reading
