"""已开始 QTE 的短暂计时颜色容错；不启动新 QTE、不外推光标。"""


class QTEPresence:
    def __init__(self):
        self.last_timer = None
        self.previous_candidate = None

    def observe(self, timer_visible, current_target, cursor, now):
        if timer_visible:
            self.last_timer = now
            self.previous_candidate = now
            return True
        previous = self.previous_candidate
        self.previous_candidate = now if current_target and cursor is not None else None
        return bool(
            self.last_timer is not None
            and 0 <= now - self.last_timer <= 0.35
            and previous is not None
            and 0 < now - previous <= 0.08
            and self.previous_candidate is not None
        )

    def invalidate(self):
        self.previous_candidate = None
