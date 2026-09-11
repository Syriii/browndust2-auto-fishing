"""黄条中心机会选择：只延后已有许可，不预测发键、不增加等待调用。"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class YellowAimDecision:
    overlap: bool | None
    reason: str
    span: tuple[int, int] | None = None
    center: float | None = None
    velocity: float | None = None
    next_step: float | None = None


def visible_yellow_span(mask, cursor):
    """实体颜色确定端点；仅修补当前光标遮住、且两侧都有黄区的小孔。"""
    height, width = mask.shape
    trim = max(1, height // 10)
    body = mask[trim:-trim]
    if not body.size:
        return None
    columns = np.count_nonzero(body, axis=0) >= max(2, body.shape[0] * 0.35)
    xs = np.flatnonzero(columns)
    if not xs.size:
        return None
    lefts, rights = xs[xs < cursor], xs[xs > cursor]
    if lefts.size and rights.size and not columns[cursor]:
        left, right = int(lefts[-1]), int(rights[0])
        if right - left - 1 <= max(3, round(height * 0.5)):
            columns[left : right + 1] = True
    edges = np.diff(np.r_[False, columns, False].astype(np.int8))
    spans = list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))
    left, right = min(spans, key=lambda span: abs((span[0] + span[1] - 1) / 2 - cursor))
    return int(left), int(right)


class YellowAim:
    """三帧稳定轨迹下，只有下一采样仍安全且更靠近中心才延后。

    不把按住/松开等待当作输入生效时延。速度异常、窄条、遮挡、反转、丢帧
    均保留原始许可；这是中心偏好，不是强制等到内部或中心。
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.velocity = None

    def _motion(self, cursor, now, span, shape):
        previous, old_velocity = self.previous, self.velocity
        self.previous, self.velocity = (cursor, now, span, shape), None
        if previous is None:
            return None
        old_x, old_time, old_span, old_shape = previous
        dt, dx = now - old_time, cursor - old_x
        stable_edges = max(2, round(shape[0] * 0.1))
        if (
            old_shape != shape
            or not 0.004 <= dt <= 0.08
            or not 0 < abs(dx) <= shape[1] * 0.15
            or max(abs(a - b) for a, b in zip(span, old_span)) > stable_edges
        ):
            return None
        self.velocity = dx / dt
        if old_velocity is None or not 0.5 <= self.velocity / old_velocity <= 2:
            return None
        return self.velocity, max(abs(old_velocity), abs(self.velocity)), dt

    def observe(self, mask, cursor, now, *, overlap, forbidden, loop_seconds):
        span = visible_yellow_span(mask, cursor)
        if span is None:
            self.reset()
            if overlap is True and _obscured_source(mask, cursor, forbidden):
                return YellowAimDecision(None, "obscured_yellow_source")
            return YellowAimDecision(overlap, "unclear_yellow")
        left, right = span
        margin = max(3, round(mask.shape[0] * 0.5))
        if forbidden[max(0, left - margin) : right + margin].any():
            self.reset()
            return YellowAimDecision(overlap, "constrained_yellow", span)
        if right - left < max(8, round(mask.shape[0] * 0.55)):
            self.reset()
            return YellowAimDecision(overlap, "narrow_yellow", span)
        motion = self._motion(cursor, now, span, mask.shape)
        center = (left + right - 1) / 2
        if motion is None:
            return YellowAimDecision(overlap, "unconfirmed_motion", span, center)
        velocity, upper_speed, dt = motion
        # 用实际采样周期与配置下限估算下一次机会，并为周期抖动留出一倍余量。
        step = upper_speed * max(dt, loop_seconds)
        distance = (center - cursor) * np.sign(velocity)
        room = right - 1 - cursor if velocity > 0 else cursor - left
        defer = overlap is True and distance > step and room > step * 2 + 1
        return YellowAimDecision(
            None if defer else overlap,
            "prefer_center" if defer else "keep_current_opportunity",
            span,
            center,
            velocity,
            step,
        )


def _obscured_source(mask, cursor, forbidden):
    """无实体竖向支持且残色紧贴障碍时，膨胀不能证明存在可按黄条。"""
    if not forbidden.any():
        return False
    columns = np.flatnonzero(mask.any(axis=0))
    if not columns.size:
        return False
    nearest = int(columns[np.abs(columns - cursor).argmin()])
    margin = max(3, round(mask.shape[0] * 0.5))
    return bool(forbidden[max(0, nearest - margin) : nearest + margin + 1].any())
