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
    diagnostics: dict | None = None


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
        self.pending_samples = None

    def begin(self, now):
        results = self.expire(now)
        ambiguous = self.pending is not None and now - self.pending[1] < 0.75
        if self.pending is not None:
            results.append(
                self.finish(
                    now,
                    "unknown",
                    None,
                    "下一次按键前没有可归属的新反馈",
                    category="superseded_by_input",
                )
            )
        self.sequence += 1
        self.pending = (self.sequence, now, ambiguous)
        self.pending_samples = dict(
            frames=0,
            unmatched_frames=0,
            unchanged_feedback_frames=0,
            unattributed_fail_events=0,
            max_frame_gap_seconds=0.0,
            max_match_score=0.0,
            last_frame_at=now,
        )
        self.recent_attempts.append((self.sequence, now))
        return results

    def finish(self, now, result, feedback, reason, score=0.0, *, category=None):
        attempt, pressed, _ = self.pending
        samples = dict(self.pending_samples)
        # 只统计原归属窗口；迟到的截图不能伪装成窗口内连续采样。
        end = min(now, pressed + 0.75)
        samples["max_frame_gap_seconds"] = max(
            samples["max_frame_gap_seconds"], end - samples["last_frame_at"]
        )
        samples["window_seconds"] = max(0, end - pressed)
        if category == "feedback_timeout":
            if samples["unattributed_fail_events"]:
                category = "fail_without_input_result"
            elif not samples["frames"]:
                category = "no_observation"
            elif samples["max_frame_gap_seconds"] > 0.20:
                category = "observation_gap"
            elif samples["unchanged_feedback_frames"]:
                category = "feedback_not_renewed"
            else:
                category = "feedback_not_detected"
        samples["category"] = category or "confirmed_feedback"
        self.pending = None
        self.pending_samples = None
        return Outcome(attempt, pressed, now, result, feedback, reason, score, diagnostics=samples)

    def expire(self, now):
        """无新截图也要按时结算，但不能把无截图当成反馈文字消失。"""
        if self.pending is not None and now - self.pending[1] > 0.75:
            return [self.finish(now, "unknown", None, "反馈等待超时", category="feedback_timeout")]
        return []

    def observe(self, label, now, score=0.0):
        if self.pending is not None and self.pending[1] <= now <= self.pending[1] + 0.75:
            samples = self.pending_samples
            samples["frames"] += 1
            samples["unmatched_frames"] += label is None
            samples["unchanged_feedback_frames"] += (
                label is not None and label == self.label and not self.blank_confirmed
            )
            samples["max_frame_gap_seconds"] = max(
                samples["max_frame_gap_seconds"], now - samples["last_frame_at"]
            )
            samples["last_frame_at"] = now
            samples["max_match_score"] = max(samples["max_match_score"], float(score))
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
            result = label
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
            if label == "fail":
                results.append(self._unattributed_fail(now, score, candidates))
                return results
            self.previous_feedback_at = now
            if self.pending is None:
                # 可能观察到接管前的输入结果，不能补造按键。
                results.append(
                    Outcome(None, None, now, result, label, "无待确认按键的新反馈", score)
                )
            elif now < self.pending[1]:
                pass  # 抓取早于按键的帧不能归给该按键。
            elif self.pending[2] and len(candidates) != 1:
                results.append(
                    self.finish(
                        now,
                        "unknown",
                        label,
                        "连续按键导致反馈归属不明确",
                        score,
                        category="ambiguous_feedback",
                    )
                )
            else:
                results.append(self.finish(now, result, label, "新出现的游戏反馈文字", score))
        return results

    def _unattributed_fail(self, now, score, candidates):
        """机制/到期 FAIL 单列，保留等待窗口与后续 HIT/MISS 的归属候选。"""
        if self.pending is not None and now >= self.pending[1]:
            self.pending_samples["unattributed_fail_events"] += 1
        return Outcome(
            None,
            None,
            now,
            "unknown",
            "fail",
            "检测到 FAIL，尚不能归因于某次按键",
            score,
            diagnostics=dict(category="unattributed_fail", candidate_attempts=candidates),
        )

    def close(self, now, reason="QTE 退出前未获得明确反馈", *, category="qte_ended"):
        return (
            [self.finish(now, "unknown", None, reason, category=category)]
            if self.pending is not None
            else []
        )
