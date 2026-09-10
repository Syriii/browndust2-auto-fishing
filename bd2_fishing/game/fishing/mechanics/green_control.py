"""绿色动作的有界状态机；输入输出都是数据，设备动作由策略统一执行。"""

from dataclasses import dataclass

from bd2_fishing.game.fishing.mechanics.regions import GreenTarget


@dataclass(frozen=True)
class GreenDecision:
    action: str
    reason: str
    started_at: float | None = None


class GreenHoldController:
    def __init__(self, *, max_hold=1.0, max_gap=0.12, margin=2):
        self.max_hold, self.max_gap, self.margin = max_hold, max_gap, margin
        self.held = False
        self.started_at = None
        self.target = None
        self.last_at = None
        self.last_cursor = None
        self.confirmations = 0
        self.clear_frames = 2
        self.consumed = False

    def release(self, reason):
        if not self.held:
            return GreenDecision("wait", reason)
        self.held = False
        self.consumed = True
        return GreenDecision("up", reason, self.started_at)

    def invalidate_observation(self):
        """断档既不能确认进入，也不能累计为确认退出；保留已消费的动作。"""
        self.confirmations = 0
        if self.clear_frames < 2:
            self.clear_frames = 0
        self.last_cursor = self.last_at = None

    def observe(self, target: GreenTarget | None, cursor, now, *, present=False, blocked=False):
        gap = self.last_at is not None and now - self.last_at > self.max_gap
        previous_cursor, previous_at = self.last_cursor, self.last_at
        self.last_at, self.last_cursor = now, cursor
        if self.held:
            if (
                gap
                or (previous_at is not None and now <= previous_at)
                or not present
                or target != self.target
                or cursor is None
                or blocked
            ):
                return self.release("green_tracking_lost")
            return self._continue_hold(target, cursor, now, previous_cursor)
        if not present:
            return self._confirm_absence(now, previous_at, gap)
        self.clear_frames = 0
        self.confirmations = (
            min(2, self.confirmations + 1) if target == self.target and not gap else 1
        )
        self.target = target
        if target is None or target.entry is None:
            return GreenDecision("wait", "green_entry_unconfirmed")
        a, b = target.entry
        if not target.left <= a < b <= target.right:
            return GreenDecision("wait", "green_entry_invalid")
        if self.consumed or self.confirmations < 2 or blocked or cursor is None:
            return GreenDecision("wait", "green_not_ready")
        if previous_at is None or now <= previous_at or previous_cursor is None or gap:
            return GreenDecision("wait", "green_direction_unconfirmed")
        delta = cursor - previous_cursor
        left_entry = a - target.left <= target.right - b
        inward = delta > 0 if left_entry else delta < 0
        if inward and a <= cursor < b:
            self.held = True
            self.started_at = now
            return GreenDecision("down", "green_entered", now)
        return GreenDecision("wait", "green_wait_entry")

    def _continue_hold(self, target, cursor, now, previous_cursor):
        if now - self.started_at >= self.max_hold:
            return self.release("green_hold_limit")
        if not target.left <= cursor < target.right:
            return self.release("green_left_region")
        entry_left, entry_right = target.entry
        left_entry = entry_left - target.left <= target.right - entry_right
        if previous_cursor is not None and (
            cursor < previous_cursor if left_entry else cursor > previous_cursor
        ):
            return self.release("green_direction_changed")
        passed_entry = (
            cursor >= entry_right + self.margin if left_entry else cursor < entry_left - self.margin
        )
        if passed_entry:
            if not target.left + self.margin <= cursor < target.right - self.margin:
                return self.release("green_release_margin_lost")
            return self.release("green_release_inside")
        return GreenDecision("wait", "green_holding", self.started_at)

    def _confirm_absence(self, now, previous_at, gap):
        if self.clear_frames < 2 and previous_at is not None and now <= previous_at:
            return GreenDecision("wait", "green_exit_confirming")
        self.clear_frames = 1 if gap and self.clear_frames < 2 else min(2, self.clear_frames + 1)
        self.confirmations = 0
        if self.clear_frames >= 2:
            self.consumed = False
            self.target = None
            return GreenDecision("normal", "green_absent")
        return GreenDecision("wait", "green_exit_confirming")
