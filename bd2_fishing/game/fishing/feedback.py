"""game.fishing.feedback：从现有实现分离的职责模块。"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import asdict
from pathlib import Path

import numpy as np

from bd2_fishing.game.fishing.feedback_rules import OutcomeTracker
from bd2_fishing.game.fishing.recognition import FeedbackMatcher
from bd2_fishing.game.fishing.scene_evidence import SceneRecorder
from bd2_fishing.infrastructure import paths as paths
from bd2_fishing.infrastructure.diagnostics import incidents
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
        self.submission_lock = threading.Lock()
        self.presses = queue.Queue(maxsize=128)
        self.dropped_presses = 0
        self.closed = False
        self.messages = []
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
        self.scenes = None
        self.scene_error = None

    def start(self):
        try:
            self.scenes = SceneRecorder(
                self.config,
                self.window,
                self.region,
                self.round_id,
                Path(paths.get_diagnostics_path()) / "qte_scenes",
            )
        except Exception as exc:
            self.scene_error = type(exc).__name__
            self.log.warning("QTE 场景取证初始化失败，反馈观察继续：%s", self.scene_error)
        self.writer = EvidenceWriter(
            Path(paths.get_diagnostics_path()) / "qte_feedback",
            self.config,
            self.region,
            self.window,
            self.config.getint("diagnostics", "failure_max_events", fallback=100),
            capture_backend="GDI screen BitBlt (BGR)",
            round_id=self.round_id,
        )
        self.thread = threading.Thread(target=self.run, name="qte-feedback-reader", daemon=True)
        self.thread.start()

    def begin_press(self, decision=None, decision_frame=None):
        """输入前只固定时间与小图并提交；不等观察锁，不归因、不输出日志。"""
        stamp = time.monotonic()
        snapshot = decision_frame.copy() if decision_frame is not None else None
        decision = dict(decision) if decision is not None else None
        with self.submission_lock:
            if self.done.is_set():
                return False
            try:
                self.presses.put_nowait((stamp, decision, snapshot))
            except queue.Full:
                self.dropped_presses += 1
                return False
        return True

    def _drain_presses(self):
        """观察或关闭时持状态锁处理；保留提交时间，不能用出队时间代替按键时间。"""
        for _ in range(self.presses.maxsize):
            try:
                stamp, decision, snapshot = self.presses.get_nowait()
            except queue.Empty:
                break
            self.publish(self.tracker.begin(stamp))
            self.press_frames[self.tracker.sequence] = [
                sample for sample in self.samples if sample[0] <= stamp
            ][-4:]
            self.press_decisions[self.tracker.sequence] = (decision, snapshot)
            if self.scenes is not None:
                self.scenes.press(self.tracker.sequence, stamp, decision)
            if decision is not None:
                self._log(
                    logging.DEBUG,
                    "QTE 按键决策: 按键序号=%d 依据=%s",
                    self.tracker.sequence,
                    json.dumps(decision, ensure_ascii=False),
                )
            if self.dropped_presses:
                # 丢记录后无法完整列举候选按键，本会话余下归属保持未知。
                self.publish(self.tracker.close(stamp, "按键记录队列溢出，归属不完整"))
                self.tracker.recent_attempts.clear()

    def _log(self, level, message, *args):
        self.messages.append((level, message, args))

    def _emit_messages(self):
        # 只有摘取列表需要状态锁；慢控制台/UI 输出不能占用该锁。
        with self.lock:
            messages, self.messages = self.messages, []
        for level, message, args in messages:
            self.log.log(level, message, *args)

    def publish(self, outcomes):
        for event in self.tracker.feedback_events[self.event_count :]:
            if self.catch_observer is not None:
                self.catch_observer.game_feedback.append(
                    dict(event, session_started_at=self.session_started_at)
                )
            self.observed_counts[event["result"]] += 1
            labels = {"critical": "暴击", "hit": "普通命中", "miss": "未命中"}
            self._log(
                logging.INFO,
                "QTE 反馈 #%d：%s（%s）",
                event["sequence"],
                labels[event["result"]],
                event["feedback"].upper(),
            )
            self._log(
                logging.DEBUG,
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
            self._log(
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
                    if (
                        self.writer is not None
                        and self.writer.submit(
                            outcome, select_evidence_frames(frames, outcome), decision_frame
                        )
                        is False
                    ):
                        self._log(logging.WARNING, "QTE 证据未入队；按键结果仍保留在本轮账本")
                else:
                    self._log(logging.WARNING, "QTE 结果无可用截图: 按键序号=%s", outcome.attempt)
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
                            if self.done.is_set():
                                break
                            incidents.observe(frame, self.region, "qte_feedback")
                            self._drain_presses()
                            self.samples.append((now, frame))
                            if self.scenes is not None and self.scene_error is None:
                                try:
                                    self.scenes.observe(frame, now)
                                except Exception as exc:
                                    self.scene_error = type(exc).__name__
                                    self._log(
                                        logging.WARNING,
                                        "QTE 场景观察异常，保留已有帧：%s",
                                        self.scene_error,
                                    )
                            self.publish(self.tracker.observe(label, now, score))
                            self.flush_evidence(now)
                        self._emit_messages()
                        if not self.done.is_set() and self.catch_observer is not None:
                            self.catch_observer.observe_timer(frame, now)
                    else:
                        with self.lock:
                            if self.done.is_set():
                                break
                            self._drain_presses()
                            self.publish(self.tracker.expire(now))
                            self.flush_evidence(now)
                        self._emit_messages()
                    self.done.wait(0.02)
        except run_control.RunStopped as exc:
            self.log.debug("QTE 观察随任务停止: %s", str(exc) or "已停止")
        except BaseException as exc:
            if not self.done.is_set():
                self.log.error(
                    "QTE 结果观察异常停止: %s；未确认的按键不会当作未命中",
                    str(exc) or type(exc).__name__,
                    exc_info=True,
                )

    def close(self):
        with self.submission_lock:
            self.done.set()
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self._drain_presses()
            if self.dropped_presses:
                self._log(
                    logging.WARNING,
                    "QTE 按键记录队列溢出：丢失=%d；后续按键归属保持未确认",
                    self.dropped_presses,
                )
            self.publish(self.tracker.close(time.monotonic()))
            if self.writer is not None:
                self.flush_evidence(time.monotonic(), force=True)
            if self.scenes is not None:
                try:
                    self.scenes.close(
                        self.tracker.feedback_events, self.scene_error or "qte_observer_closed"
                    )
                    if self.scenes.submitted is False:
                        self._log(logging.WARNING, "QTE 场景证据队列已满，本轮场景记录未保存")
                except Exception as exc:
                    self._log(logging.WARNING, "QTE 场景证据提交失败：%s", type(exc).__name__)
            if self.catch_observer is not None:
                self.catch_observer.stop_observing()
                self.catch_observer.feedback_diagnostics = dict(
                    dropped_press_records=self.dropped_presses,
                    attribution_incomplete=bool(self.dropped_presses),
                    scene_observation_error=self.scene_error,
                    scene_evidence_submitted=self.scenes.submitted
                    if self.scenes is not None
                    else None,
                )
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.catch_observer is not None:
                self.catch_observer.feedback_diagnostics["reader_still_running"] = (
                    self.thread.is_alive()
                )
        if self.writer is not None:
            self.writer.close()
        # 仅在本轮观察关闭后有界等待写盘，不阻塞逐帧检测或按键路径。
        if self.scenes is not None and self.scenes.submitted and not self.scenes.done.wait(1):
            self.log.warning("QTE 场景证据仍在后台写入")
        self._emit_messages()
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
