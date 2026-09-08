"""可选 QTE 结果观察器。只读游戏反馈，不参与选择光标、按键或流程退出。"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass
import itertools
import json
import logging
from pathlib import Path
import queue
import threading
import time
import uuid
import run_control
from zipfile import ZIP_STORED, ZipFile

import cv2
import numpy as np

from logging_context import get_logger, current_round_id, fishing_round
log = get_logger(__name__)
_slots = itertools.count()


def white_text(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 185), (180, 105, 255))
    return cv2.GaussianBlur(mask, (3, 3), .8)


class FeedbackMatcher:
    """仅匹配实测反馈字形；不以按键位置或进度变化推测命中。"""
    def __init__(self, width, height, assets=None):
        assets = Path(assets or Path(__file__).with_name("qte_feedback_assets"))
        self.patterns = {}
        for name in ("critical", "critical_alt", "hit", "miss", "fail"):
            image = cv2.imdecode(np.frombuffer((assets / f"{name}.png").read_bytes(), np.uint8), 1)
            if image is None:
                raise ValueError(f"反馈模板无法解码: {name}")
            # 模板来自 875×492 客户区；匹配在当前位置搜索，不固定字样的动画坐标。
            image = cv2.resize(image, (max(1, round(image.shape[1]*width/875)),
                                       max(1, round(image.shape[0]*height/492))))
            self.patterns.setdefault(name.split("_")[0], []).append(white_text(image))

    def detect(self, frame):
        mask = white_text(frame)
        scores = []
        for name, patterns in self.patterns.items():
            group = []
            for pattern in patterns:
                if mask.shape[0] >= pattern.shape[0] and mask.shape[1] >= pattern.shape[1]:
                    group.append(float(cv2.minMaxLoc(cv2.matchTemplate(mask, pattern, cv2.TM_CCOEFF_NORMED))[1]))
            if group:
                scores.append((max(group), name))
        scores.sort(reverse=True)
        if not scores or scores[0][0] < .80:
            return None, scores[0][0] if scores else 0.0
        if len(scores) > 1 and scores[0][0]-scores[1][0] < .12:
            return None, scores[0][0]
        return scores[0][1], scores[0][0]


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
        ambiguous = self.pending is not None and now-self.pending[1] < .75
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
        if self.pending is not None and now-self.pending[1] > .75:
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
            if self.blank_since is None or now-self.last_sample_at > .20:
                self.blank_since = now
            # 至少实际观察到跨越 100 ms 的空白；单张坏帧加采集停顿不能重新计数。
            self.blank_confirmed = self.blank_confirmed or now-self.blank_since >= .10
        self.last_sample_at = now
        if fresh:
            result = "miss" if label in ("miss", "fail") else label
            candidates = [attempt for attempt, stamp in self.recent_attempts
                          if now-.75 <= stamp <= now and stamp > self.previous_feedback_at]
            self.feedback_events.append(dict(sequence=len(self.feedback_events)+1, observed_at=now,
                result=result, feedback=label, score=score, candidate_attempts=candidates))
            self.previous_feedback_at = now
            if self.pending is None:
                # 无对应按键的 FAIL 原因未确认；蓝区缩完等也可能触发，不能反推某次输入失败。
                results.append(Outcome(None, None, now, result, label, "无待确认按键的新反馈", score))
            elif now < self.pending[1]:
                pass  # 抓取早于按键的帧不能归给该按键。
            elif self.pending[2] and len(candidates) != 1:
                results.append(self.finish(now, "unknown", label, "连续按键导致反馈归属不明确", score))
            else:
                results.append(self.finish(now, result, label, "新出现的游戏反馈文字", score))
        return results

    def close(self, now, reason="QTE 退出前未获得明确反馈"):
        return [self.finish(now, "unknown", None, reason)] if self.pending is not None else []


def select_evidence_frames(frames, outcome, limit=8):
    """保留反馈发生帧和按键前后帧，再用均匀抽样补足上下文。"""
    if len(frames) <= limit:
        return frames
    stamps = [stamp for stamp, _ in frames]
    selected = {0, len(frames)-1,
                min(range(len(frames)), key=lambda i: abs(stamps[i]-outcome.observed_at))}
    if outcome.pressed_at is not None:
        before = [i for i, stamp in enumerate(stamps) if stamp <= outcome.pressed_at]
        after = [i for i, stamp in enumerate(stamps) if stamp >= outcome.pressed_at]
        if before:
            selected.add(before[-1])
        if after:
            selected.add(after[0])
    for i in np.linspace(0, len(frames)-1, limit, dtype=int):
        if len(selected) >= limit:
            break
        selected.add(int(i))
    return [frames[i] for i in sorted(selected)]


class EvidenceWriter:
    """小 ROI 原图及同帧掩膜在后台编码；队列与磁盘槽位均有上限。"""
    def __init__(self, directory, config, region, window, max_events=10, capture_backend="unspecified BGR source", round_id=None):
        self.directory, self.config = Path(directory), config
        self.region, self.window = region, window
        self.round_id = round_id or current_round_id()
        self.log = get_logger(__name__, self.round_id)
        self.capture_backend = capture_backend
        self.max_events = max(1, max_events)
        self.queue = queue.Queue(maxsize=2)
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.run, name="qte-evidence", daemon=True)
        self.thread.start()

    def submit(self, outcome, samples, decision_frame=None):
        try:
            self.queue.put_nowait((outcome, samples, decision_frame))
        except queue.Full:
            self.log.warning("QTE 证据保存队列已满；此次未保存截图，按键结果仍保留在日志")

    def run(self):
        while not self.done.is_set() or not self.queue.empty():
            try:
                outcome, samples, decision_frame = self.queue.get(timeout=.05)
            except queue.Empty:
                continue
            try:
                self.save(outcome, samples, decision_frame)
            except Exception:
                self.log.exception("QTE 证据保存失败；不改变钓鱼控制")

    def save(self, outcome, samples, decision_frame=None):
        import utils
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"qte_{next(_slots) % self.max_events + 1:02d}.zip"
        temporary = path.with_suffix(".tmp")
        ranges = {name: utils.read_hsv_range(self.config, "roi", name)
                  for name in ("white", "yellow", "blue")}
        evidence_id = uuid.uuid4().hex
        metadata = dict(round_id=self.round_id, evidence_id=evidence_id, outcome=asdict(outcome), window_region=self.window.as_tuple(),
                        capture_backend=self.capture_backend,
                        evidence_region=self.region.as_tuple(), saved_at_unix=time.time(),
                        frames=[], hsv={k: dict(lower=v.lower.tolist(), upper=v.upper.tolist()) for k,v in ranges.items()},
                        decision_frame_available=decision_frame is not None,
                        note="仅 QTE 结果证据；frame_* 是独立观察帧，decision.png（若有）是该次按键的控制决策原图。各自掩膜与原图同帧，原始颜色掩膜不含策略膨胀。不含真假指针判定，不是整条鱼捕获结果。")
        with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
            if decision_frame is not None:
                metadata["decision_frame"] = dict(file="decision.png", shape=list(decision_frame.shape),
                    captured_at_monotonic=(outcome.decision or {}).get("captured_at_monotonic"),
                    frame_region=(outcome.decision or {}).get("frame_region"))
                hsv = cv2.cvtColor(decision_frame, cv2.COLOR_BGR2HSV)
                images = {"decision.png": decision_frame}
                images.update({f"decision_{k}.png": cv2.inRange(hsv, v.lower, v.upper) for k,v in ranges.items()})
                for filename, image in images.items():
                    ok, data = cv2.imencode(".png", image)
                    if not ok:
                        raise RuntimeError("QTE 决策证据 PNG 编码失败")
                    archive.writestr(filename, data.tobytes())
            for i, (stamp, frame) in enumerate(samples):
                name = f"frame_{i:02d}.png"
                metadata["frames"].append(dict(file=name, captured_at_monotonic=stamp,
                    relative_to_press_ms=None if outcome.pressed_at is None else (stamp-outcome.pressed_at)*1000,
                    relative_to_feedback_ms=(stamp-outcome.observed_at)*1000))
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                images = {name: frame}
                images.update({f"frame_{i:02d}_{k}.png": cv2.inRange(hsv, v.lower, v.upper)
                               for k,v in ranges.items()})
                for filename, image in images.items():
                    ok, data = cv2.imencode(".png", image)
                    if not ok:
                        raise RuntimeError("QTE 证据 PNG 编码失败")
                    archive.writestr(filename, data.tobytes())
            archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        temporary.replace(path)
        self.log.debug("QTE 证据已保存: %s；证据ID=%s 按键=%s 帧数=%d", path, evidence_id, outcome.attempt, len(samples))

    def close(self):
        self.done.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            self.log.warning("QTE 证据仍在后台写入")


class FeedbackSession:
    """独立只读采集小区域；生产按键仍调用原 controlled_input.press。"""
    def __init__(self, config, window, catch_observer=None):
        import utils
        self.config, self.window = config, window
        self.catch_observer = catch_observer
        self.round_id = catch_observer.round_id if catch_observer is not None else (current_round_id() or uuid.uuid4().hex[:12])
        self.log = get_logger(__name__, self.round_id)
        self.session_started_at = time.monotonic()
        self.region = utils.Rect(window.left+round(window.width*.30),
                                 window.top+round(window.height*.64),
                                 window.left+round(window.width*.70),
                                 window.top+round(window.height*.93))
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
        import utils
        self.writer = EvidenceWriter(Path(utils.get_base_path())/"debug"/"qte_feedback",
                                     self.config, self.region, self.window,
                                     self.config.getint("diagnostics", "max_events", fallback=10),
                                     capture_backend="GDI screen BitBlt (BGR)", round_id=self.round_id)
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
                self.log.debug("QTE 按键决策: 按键序号=%d 依据=%s", self.tracker.sequence,
                               json.dumps(decision, ensure_ascii=False))

    def publish(self, outcomes):
        for event in self.tracker.feedback_events[self.event_count:]:
            if self.catch_observer is not None:
                self.catch_observer.game_feedback.append(dict(event, session_started_at=self.session_started_at))
            self.observed_counts[event["result"]] += 1
            labels = {"critical": "暴击", "hit": "普通命中", "miss": "未命中"}
            self.log.info("QTE 反馈 #%d：%s（%s）", event["sequence"], labels[event["result"]], event["feedback"].upper())
            self.log.debug("QTE 反馈依据: 序号=%d 结果=%s 文字=%s 候选按键=%s 匹配=%.3f",
                     event["sequence"], event["result"], event["feedback"],
                     event["candidate_attempts"], event["score"])
        self.event_count = len(self.tracker.feedback_events)
        for outcome in outcomes:
            outcome.decision, decision_frame = self.press_decisions.pop(outcome.attempt, (None, None))
            if self.catch_observer is not None:
                self.catch_observer.attempt_outcomes.append(dict(asdict(outcome), session_started_at=self.session_started_at))
            target = self.counts if outcome.attempt is not None else self.unassigned
            target[outcome.result] += 1
            level = logging.DEBUG
            labels = {"critical": "暴击", "hit": "普通命中", "miss": "未命中", "unknown": "未确认"}
            self.log.log(level, "QTE 按键归属: 按键序号=%s 结果=%s 反馈=%s 原因=%s 匹配=%.3f",
                    outcome.attempt, labels[outcome.result], outcome.feedback, outcome.reason, outcome.score)
            before = self.press_frames.pop(outcome.attempt, [])
            if outcome.result in ("miss", "unknown"):
                self.pending_evidence.append((outcome.observed_at+.25, outcome, before+list(self.samples), decision_frame))

    def flush_evidence(self, now, force=False):
        pending = []
        for deadline, outcome, before, decision_frame in self.pending_evidence:
            if force or now >= deadline:
                earliest = outcome.pressed_at-.15 if outcome.pressed_at is not None else outcome.observed_at-.55
                frames = {stamp: frame for stamp,frame in before+list(self.samples)
                          if earliest <= stamp <= outcome.observed_at+.25}
                frames = sorted(frames.items())
                if frames or decision_frame is not None:
                    self.writer.submit(outcome, select_evidence_frames(frames, outcome), decision_frame)
                else:
                    self.log.warning("QTE 结果无可用截图: 按键序号=%s", outcome.attempt)
            else:
                pending.append((deadline, outcome, before, decision_frame))
        self.pending_evidence = pending

    def run(self):
        with fishing_round(self.round_id):
            self._observe()

    def _observe(self):
        import utils
        from feedback_capture import FeedbackCapture
        utils.enable_dpi_awareness()
        try:
            guard = utils.WindowGuard("BrownDust II", self.window, require_foreground=True)
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
                        text_height = round(self.window.height*.18)
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
                    self.done.wait(.02)
        except run_control.RunStopped as exc:
            self.log.debug("QTE 观察随任务停止: %s", str(exc) or "已停止")
        except BaseException as exc:
            self.log.error("QTE 结果观察异常停止: %s；未确认的按键不会当作未命中",
                        str(exc) or type(exc).__name__, exc_info=True)

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
        self.log.debug("QTE 按键归属统计: 尝试=%d 暴击=%d 普通命中=%d 未命中=%d 未确认=%d 无对应按键反馈=%s",
                 self.tracker.sequence, self.counts["critical"], self.counts["hit"],
                 self.counts["miss"], self.counts["unknown"], dict(self.unassigned))
        self.log.log(logging.INFO if self.catch_observer is None else logging.DEBUG, "QTE 游戏反馈统计: 总数=%d 暴击=%d 普通命中=%d 未命中=%d（按反馈去重，不等于按键次数）",
                 self.event_count, self.observed_counts["critical"], self.observed_counts["hit"],
                 self.observed_counts["miss"])
