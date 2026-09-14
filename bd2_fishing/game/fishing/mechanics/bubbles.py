"""泡泡球的一次输入许可；纯状态计算，不等待、不读取游戏或写文件。"""


class BubbleController:
    def __init__(self):
        self.span = None
        self.confirmations = 0
        self.consumed = False
        self.absent_since = None
        self.previous_at = None
        self.replacement_confirmations = 0
        self.replacement_span = None

    def invalidate_observation(self):
        self.confirmations = 0
        self.previous_at = None
        self.absent_since = None
        self.replacement_confirmations = 0
        self.replacement_span = None

    def observe(self, spans, cursor, now, *, blocked=False, uncertain=False):
        fresh = self.previous_at is None or 0 < now - self.previous_at <= 0.25
        self.previous_at = now
        if not fresh:
            self.confirmations = 0
            self.absent_since = None
        if len(spans) != 1:
            self.confirmations = 0
            self.replacement_confirmations = 0
            self.replacement_span = None
            if uncertain or spans:
                self.absent_since = None
            elif self.absent_since is None:
                self.absent_since = now
            elif now - self.absent_since >= 0.3:
                self.span = None
                self.consumed = False
            return False
        self.absent_since = None
        span = spans[0]
        if not self._confirm_replacement(span, fresh):
            return False
        same = self.span is not None and abs(sum(span) - sum(self.span)) <= max(
            6, (span[1] - span[0]) * 0.4
        )
        self.confirmations = min(2, self.confirmations + 1) if same and fresh else 1
        self.span = span
        if self.consumed or self.confirmations < 2 or cursor is None or blocked:
            return False
        # 只在球体中部单击，避免描边抖动；未知或暗指针不能授权输入。
        left, right = span
        inset = max(3, round((right - left) * 0.3))
        if left + inset <= cursor < right - inset:
            self.consumed = True
            return True
        return False

    def _confirm_replacement(self, span, fresh):
        """同一旧球不解锁；不相交的新位置必须在新鲜观测中连续出现。"""
        # 旧球按过后，新球可能在另一位置立即出现；不能把旧球的一次性锁带过去。
        separate = self.span is not None and (span[1] <= self.span[0] or span[0] >= self.span[1])
        if self.consumed and separate:
            stable = (
                self.replacement_span is not None
                and max(abs(a - b) for a, b in zip(span, self.replacement_span)) <= 3
            )
            self.replacement_confirmations = (
                self.replacement_confirmations + 1 if fresh and stable else 1
            )
            self.replacement_span = span
            if self.replacement_confirmations < 2:
                return False
            self.consumed = False
            self.span, self.confirmations = span, 1
        else:
            self.replacement_confirmations = 0
            self.replacement_span = None
        return True
