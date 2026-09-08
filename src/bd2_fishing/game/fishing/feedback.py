"""game.fishing.feedback：从现有实现分离的职责模块。"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import asdict
from pathlib import Path

import numpy as np

from bd2_fishing.game.fishing.feedback_rules import OutcomeTracker
from bd2_fishing.game.fishing.recognition import FeedbackMatcher
from bd2_fishing.infrastructure import paths as paths
from bd2_fishing.infrastructure.diagnostics.qte_evidence import EvidenceWriter
from bd2_fishing.infrastructure.windows import window as window
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime import geometry as geometry
from bd2_fishing.runtime.context import current_round_id, fishing_round, get_logger

log = get_logger(__name__)


def select_evidence_frames(frames, outcome, limit=8):
    """保留反馈发生帧和按键前后帧，再用均匀抽样补足上下文。"""
    if len(frames) <= limit:
        return frames
    stamps = [stamp for stamp, _ in frames]
    selected = {
        0,
        len(frames) - 1,
        min(range(len(frames)), key=lambda i: abs(stamps[i] - outcome.observed_at)),
    }
    if outcome.pressed_at is not None:
        before = [i for i, stamp in enumerate(stamps) if stamp <= outcome.pressed_at]
        after = [i for i, stamp in enumerate(stamps) if stamp >= outcome.pressed_at]
        if before:
            selected.add(before[-1])
        if after:
            selected.add(after[0])
    for i in np.linspace(0, len(frames) - 1, limit, dtype=int):
        if len(selected) >= limit:
            break
        selected.add(int(i))
    return [frames[i] for i in sorted(selected)]


class FeedbackSession:
    """独立只读采集小区域；生产按键仍调用原 controlled_input.press。"""

    def __init__(self, config, window, catch_observer=None):
        self.config, self.window = config, window
        self.catch_observer = catch_observer
        self.round_id = (
            catch_observer.round_id
            if catch_observer is not None
            else (current_round_id() or uuid.uuid4().hex[:12])
        )
        self.log = get_logger(__name__, self.round_id)
        self.session_started_at = time.monotonic()
        self.region = geometry.Rect(
            window.left + round(window.width * 0.30),
            window.top + round(window.height * 0.64),
            window.left + round(window.width * 0.70),
            window.top + round(window.height * 0.93),
        )
        self.matcher = FeedbackMatcher(window.width, window.height)
        self.tracker = OutcomeTracker()
        self.samples = deque(maxlen=24)
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.thread = None
        self.writer = None
        self.pending_evidence = []
        self.press_frames = {}
        self.press_decisions = {}
        self.counts = Counter()
        self.unassigned = Counter()
        self.event_count = 0
        self.observed_counts = Counter()

    def start(self):
        self.writer = EvidenceWriter(
            Path(paths.get_diagnostics_path()) / "qte_feedback",
            self.config,
            self.region,
            self.window,
            self.config.getint("diagnostics", "max_events", fallback=10),
            capture_backend="GDI screen BitBlt (BGR)",
            round_id=self.round_id,
        )
        self.thread = threading.Thread(target=self.run, name="qte-feedback-reader", daemon=True)
        self.thread.start()

    def begin_press(self, decision=None, decision_frame=None):
        # 在原按键调用前只复制小区域；编码与写盘仍由后台完成。
        snapshot = decision_frame.copy() if decision_frame is not None else None
        decision = dict(decision) if decision is not None else None
        with self.lock:
            self.publish(self.tracker.begin(time.monotonic()))
            self.press_frames[self.tracker.sequence] = list(self.samples)[-4:]
            self.press_decisions[self.tracker.sequence] = (decision, snapshot)
            if decision is not None:
                self.log.debug(
                    "QTE 按键决策: 按键序号=%d 依据=%s",
                    self.tracker.sequence,
                    json.dumps(decision, ensure_ascii=False),
                )

    def publish(self, outcomes):
        for event in self.tracker.feedback_events[self.event_count :]:
            if self.catch_observer is not None:
                self.catch_observer.game_feedback.append(
                    dict(event, session_started_at=self.session_started_at)
                )
            self.observed_counts[event["result"]] += 1
            labels = {"critical": "暴击", "hit": "普通命中", "miss": "未命中"}
            self.log.info(
                "QTE 反馈 #%d：%s（%s）",
                event["sequence"],
                labels[event["result"]],
                event["feedback"].upper(),
            )
            self.log.debug(
                "QTE 反馈依据: 序号=%d 结果=%s 文字=%s 候选按键=%s 匹配=%.3f",
                event["sequence"],
                event["result"],
                event["feedback"],
                event["candidate_attempts"],
                event["score"],
            )
        self.event_count = len(self.tracker.feedback_events)
        for outcome in outcomes:
            outcome.decision, decision_frame = self.press_decisions.pop(
                outcome.attempt, (None, None)
            )
            if self.catch_observer is not None:
                self.catch_observer.attempt_outcomes.append(
                    dict(asdict(outcome), session_started_at=self.session_started_at)
                )
            target = self.counts if outcome.attempt is not None else self.unassigned
            target[outcome.result] += 1
            level = logging.DEBUG
            labels = {"critical": "暴击", "hit": "普通命中", "miss": "未命中", "unknown": "未确认"}
            self.log.log(
                level,
                "QTE 按键归属: 按键序号=%s 结果=%s 反馈=%s 原因=%s 匹配=%.3f",
                outcome.attempt,
                labels[outcome.result],
                outcome.feedback,
                outcome.reason,
                outcome.score,
            )
            before = self.press_frames.pop(outcome.attempt, [])
            if outcome.result in ("miss", "unknown"):
                self.pending_evidence.append(
                    (
                        outcome.observed_at + 0.25,
                        outcome,
                        before + list(self.samples),
                        decision_frame,
                    )
                )

    def flush_evidence(self, now, force=False):
        pending = []
        for deadline, outcome, before, decision_frame in self.pending_evidence:
            if force or now >= deadline:
                earliest = (
                    outcome.pressed_at - 0.15
                    if outcome.pressed_at is not None
                    else outcome.observed_at - 0.55
                )
                frames = {
                    stamp: frame
                    for stamp, frame in before + list(self.samples)
                    if earliest <= stamp <= outcome.observed_at + 0.25
                }
                frames = sorted(frames.items())
                if frames or decision_frame is not None:
                    self.writer.submit(
                        outcome, select_evidence_frames(frames, outcome), decision_frame
                    )
                else:
                    self.log.warning("QTE 结果无可用截图: 按键序号=%s", outcome.attempt)
            else:
                pending.append((deadline, outcome, before, decision_frame))
        self.pending_evidence = pending

    def run(self):
        with fishing_round(self.round_id):
            self._observe()

    def _observe(self):
        from bd2_fishing.infrastructure.windows.gdi import FeedbackCapture

        window.enable_dpi_awareness()
        try:
            guard = window.WindowGuard("BrownDust II", self.window, require_foreground=True)
            with FeedbackCapture(self.region) as camera:
                while not self.done.is_set():
                    guard()
                    frame = camera.grab()
                    now = time.monotonic()
                    if self.done.is_set():
                        break
                    if frame is not None:
                        frame = frame.copy()
                        # 仅上方文字区域参与匹配，下方 QTE 条保留在证据帧中。
                        text_height = round(self.window.height * 0.18)
                        label, score = self.matcher.detect(frame[:text_height])
                        with self.lock:
                            self.samples.append((now, frame))
                            self.publish(self.tracker.observe(label, now, score))
                            self.flush_evidence(now)
                        if self.catch_observer is not None:
                            self.catch_observer.observe_timer(frame, now)
                    else:
                        with self.lock:
                            self.publish(self.tracker.expire(now))
                            self.flush_evidence(now)
                    self.done.wait(0.02)
        except run_control.RunStopped as exc:
            self.log.debug("QTE 观察随任务停止: %s", str(exc) or "已停止")
        except BaseException as exc:
            self.log.error(
                "QTE 结果观察异常停止: %s；未确认的按键不会当作未命中",
                str(exc) or type(exc).__name__,
                exc_info=True,
            )

    def close(self):
        self.done.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        with self.lock:
            self.publish(self.tracker.close(time.monotonic()))
            if self.writer is not None:
                self.flush_evidence(time.monotonic(), force=True)
        if self.writer is not None:
            self.writer.close()
        self.log.debug(
            "QTE 按键归属统计: 尝试=%d 暴击=%d 普通命中=%d 未命中=%d 未确认=%d 无对应按键反馈=%s",
            self.tracker.sequence,
            self.counts["critical"],
            self.counts["hit"],
            self.counts["miss"],
            self.counts["unknown"],
            dict(self.unassigned),
        )
        self.log.log(
            logging.INFO if self.catch_observer is None else logging.DEBUG,
            "QTE 游戏反馈统计: 总数=%d 暴击=%d 普通命中=%d 未命中=%d（按反馈去重，不等于按键次数）",
            self.event_count,
            self.observed_counts["critical"],
            self.observed_counts["hit"],
            self.observed_counts["miss"],
        )
