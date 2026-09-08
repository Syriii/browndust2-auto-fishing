"""game.fishing.feedback_rules：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Outcome:
    attempt: int | None
    pressed_at: float | None
    observed_at: float
    result: str
    feedback: str | None
    reason: str
    score: float = 0.0
    decision: dict | None = None


class OutcomeTracker:
    """每次调用最多结算一次；无反馈不等于未命中，连续动作无法归属时保留未知。"""

    def __init__(self):
        self.sequence = 0
        self.pending = None
        self.label = None
        self.blank_since = None
        self.blank_confirmed = False
        self.last_sample_at = float("-inf")
        self.recent_attempts = deque(maxlen=32)
        self.feedback_events = []
        self.previous_feedback_at = float("-inf")

    def begin(self, now):
        results = []
        ambiguous = self.pending is not None and now - self.pending[1] < 0.75
        if self.pending is not None:
            results.append(self.finish(now, "unknown", None, "下一次按键前没有可归属的新反馈"))
        self.sequence += 1
        self.pending = (self.sequence, now, ambiguous)
        self.recent_attempts.append((self.sequence, now))
        return results

    def finish(self, now, result, feedback, reason, score=0.0):
        attempt, pressed, _ = self.pending
        self.pending = None
        return Outcome(attempt, pressed, now, result, feedback, reason, score)

    def expire(self, now):
        """无新截图也要按时结算，但不能把无截图当成反馈文字消失。"""
        if self.pending is not None and now - self.pending[1] > 0.75:
            return [self.finish(now, "unknown", None, "反馈等待超时")]
        return []

    def observe(self, label, now, score=0.0):
        results = self.expire(now)
        fresh = label is not None and (label != self.label or self.blank_confirmed)
        if label is not None:
            self.label = label
            self.blank_since = None
            self.blank_confirmed = False
        else:
            if self.blank_since is None or now - self.last_sample_at > 0.20:
                self.blank_since = now
            # 至少实际观察到跨越 100 ms 的空白；单张坏帧加采集停顿不能重新计数。
            self.blank_confirmed = self.blank_confirmed or now - self.blank_since >= 0.10
        self.last_sample_at = now
        if fresh:
            result = "miss" if label in ("miss", "fail") else label
            candidates = [
                attempt
                for attempt, stamp in self.recent_attempts
                if now - 0.75 <= stamp <= now and stamp > self.previous_feedback_at
            ]
            self.feedback_events.append(
                dict(
                    sequence=len(self.feedback_events) + 1,
                    observed_at=now,
                    result=result,
                    feedback=label,
                    score=score,
                    candidate_attempts=candidates,
                )
            )
            self.previous_feedback_at = now
            if self.pending is None:
                # 无对应按键的 FAIL 原因未确认；蓝区缩完等也可能触发，不能反推某次输入失败。
                results.append(
                    Outcome(None, None, now, result, label, "无待确认按键的新反馈", score)
                )
            elif now < self.pending[1]:
                pass  # 抓取早于按键的帧不能归给该按键。
            elif self.pending[2] and len(candidates) != 1:
                results.append(
                    self.finish(now, "unknown", label, "连续按键导致反馈归属不明确", score)
                )
            else:
                results.append(self.finish(now, result, label, "新出现的游戏反馈文字", score))
        return results

    def close(self, now, reason="QTE 退出前未获得明确反馈"):
        return [self.finish(now, "unknown", None, reason)] if self.pending is not None else []
