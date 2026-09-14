"""黄条中心机会选择：只延后已有许可，不预测发键、不增加等待调用。"""

from dataclasses import dataclass

import numpy as np

from bd2_fishing.game.fishing.mechanics.yellow_geometry import read_yellow_geometry


@dataclass(frozen=True)
class YellowAimDecision:
    overlap: bool | None
    reason: str
    span: tuple[int, int] | None = None
    center: float | None = None
    velocity: float | None = None
    next_step: float | None = None


def visible_yellow_span(mask, cursor, *, forbidden=None):
    return read_yellow_geometry(mask, cursor, forbidden).span


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

    def observe(self, mask, cursor, now, *, overlap, forbidden, loop_seconds, span=...):
        if span is ...:
            span = visible_yellow_span(mask, cursor, forbidden=forbidden)
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


def supported_yellow_overlap(mask, cursor, overlap, *, forbidden=None, span=...):
    """膨胀只修补光标孔洞，不能靠外溢色块在实体黄条外授权输入。"""
    if overlap is not True:
        return overlap
    if span is ...:
        span = visible_yellow_span(mask, cursor, forbidden=forbidden)
    if span is None:
        return None
    left, right = span
    # 保留少量抗锯齿容差；1–2 列残片不足以确定一个可按目标。
    margin = max(1, round(mask.shape[0] * 0.1))
    if right - left < max(3, round(mask.shape[0] * 0.16)):
        return None
    return True if left - margin <= cursor < right + margin else None


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
