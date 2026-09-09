"""复用观察帧记录特殊场景及整轮低频时间线，独立于命中/失败结果。"""

import threading
import time
import uuid
from collections import Counter, deque
from pathlib import Path

from bd2_fishing.game.fishing.pointer import PointerMotion
from bd2_fishing.game.fishing.scene_signals import SceneSignals
from bd2_fishing.infrastructure.diagnostics import bundle_writer


class SceneRecorder:
    """仅由反馈观察器状态锁内调用；编码/写盘交给通用后台写入器。"""

    MAX_FRAMES = 80
    MAX_BYTES = 12 * 1024 * 1024
    MAX_FRAME_BYTES = 6 * 1024 * 1024

    def __init__(self, config, window, region, round_id, directory):
        self.config, self.window, self.region = config, window, region
        self.round_id, self.directory = round_id, Path(directory)
        self.signals = SceneSignals(config, window, region)
        self.motion = PointerMotion()
        self.interval = max(0.5, config.getfloat("time", "longest_keep_time") / 32)
        self.recent = deque(maxlen=4)
        self.frames = {}
        self.events = []
        self.attempts = deque(maxlen=128)
        self.seen = Counter()
        self.previous_signals = set()
        self.last_event = float("-inf")
        self.last_periodic = float("-inf")
        self.last_burst = float("-inf")
        self.burst_until = float("-inf")
        self.bytes = self.dropped_frames = self.dropped_events = 0
        self.drop_reasons = Counter()
        self.first_signals = set()
        self.closed = False
        self.done = threading.Event()
        self.done.set()
        self.submitted = None
        self.last_observed = None
        self.sample_gaps = 0

    def press(self, attempt, stamp, decision):
        if not self.closed:
            self.attempts.append(dict(attempt=attempt, pressed_at=stamp, decision=decision))

    def _keep(self, sample, kind):
        stamp, frame, features = sample
        priorities = {"periodic": 0, "candidate": 1, "first_candidate": 2, "final": 3}
        if stamp in self.frames:
            if priorities[kind] > priorities[self.frames[stamp][2]]:
                self.frames[stamp][2] = kind
            return
        while self.frames and (
            len(self.frames) >= self.MAX_FRAMES or self.bytes + frame.nbytes > self.MAX_BYTES
        ):
            # 后来的普通帧不能挤掉异常代表帧；同优先级按采集时间淘汰。
            victim = min(
                self.frames,
                key=lambda t: (priorities[self.frames[t][2]], t),
            )
            if priorities[kind] < priorities[self.frames[victim][2]]:
                self.dropped_frames += 1
                self.drop_reasons[f"rejected_{kind}"] += 1
                return
            old = self.frames.pop(victim)
            self.bytes -= old[0].nbytes
            self.dropped_frames += 1
            self.drop_reasons[f"evicted_{old[2]}"] += 1
        self.frames[stamp] = [frame, features, kind]
        self.bytes += frame.nbytes

    def observe(self, frame, stamp):
        if self.closed:
            return
        if frame.nbytes > min(self.MAX_FRAME_BYTES, self.MAX_BYTES):
            self.dropped_frames += 1
            self.drop_reasons["oversized"] += 1
            return
        signals, features = self.signals.inspect(frame)
        features["pointer_motion"] = self.motion.observe(
            features.get("bright_cursor_x"),
            stamp,
            tuple(features.get("qte_shape", ())),
            active=features.get("qte_active", False),
        )
        sample = (stamp, frame.copy(), features)
        if self.last_observed is not None and stamp - self.last_observed > 0.3:
            self.seen.clear()
            self.previous_signals.clear()
            self.recent.clear()
            self.sample_gaps += 1
        self.last_observed = stamp
        current = set(signals)
        self.seen = Counter({name: self.seen[name] + 1 for name in current})
        confirmed = {name for name in current if self.seen[name] >= 2}
        new_signals = confirmed - self.previous_signals
        trigger = bool(confirmed) and (
            (bool(new_signals) and stamp - self.last_event >= 0.5) or stamp - self.last_event >= 3
        )
        if trigger:
            if len(self.events) < 64:
                self.events.append(
                    dict(
                        observed_at=stamp,
                        candidates=sorted(confirmed),
                        features=features,
                        classification="unconfirmed",
                    )
                )
            else:
                self.dropped_events += 1
            self.last_event = stamp
            self.burst_until = stamp + 0.4
            for before in self.recent:
                self._keep(before, "candidate")
            first = bool(confirmed - self.first_signals)
            self._keep(sample, "first_candidate" if first else "candidate")
            self.first_signals.update(confirmed)
        if stamp <= self.burst_until and stamp - self.last_burst >= 0.08:
            self._keep(sample, "candidate")
            self.last_burst = stamp
        if stamp - self.last_periodic >= self.interval:
            self._keep(sample, "periodic")
            self.last_periodic = stamp
        self.previous_signals = confirmed
        self.recent.append(sample)

    def close(self, feedback, reason):
        if self.closed:
            return
        self.closed = True
        if self.recent:
            self._keep(self.recent[-1], "final")
        if not self.frames and not self.dropped_frames:
            return
        category = "candidates" if self.events else "routine"
        images, records = {}, []
        for i, (stamp, (frame, features, kind)) in enumerate(sorted(self.frames.items())):
            filename = f"frame_{i:03d}.png"
            images[filename] = frame
            records.append(
                dict(file=filename, captured_at_monotonic=stamp, selection=kind, features=features)
            )
        metadata = dict(
            evidence_id=uuid.uuid4().hex,
            round_id=self.round_id,
            event="qte_scene_observation",
            saved_at_unix=time.time(),
            capture_backend="GDI screen BitBlt (BGR)",
            evidence_region=self.region.as_tuple(),
            window_region=self.window.as_tuple(),
            control_region=self.signals.control_region.as_tuple(),
            crops=self.signals.crops,
            frames=records,
            candidates=[
                dict(
                    event,
                    evidence_file=next(
                        (
                            record["file"]
                            for record in records
                            if record["captured_at_monotonic"] == event["observed_at"]
                        ),
                        None,
                    ),
                )
                for event in self.events
            ],
            attempts=list(self.attempts),
            feedback=list(feedback),
            close_reason=reason,
            dropped_frames=self.dropped_frames,
            dropped_frame_reasons=dict(self.drop_reasons),
            dropped_events=self.dropped_events,
            sample_gaps=self.sample_gaps,
            hsv={
                name: dict(lower=color.lower.tolist(), upper=color.upper.tolist())
                for name, color in self.signals.ranges.items()
            },
            appearance_hsv={
                name: dict(lower=list(lower), upper=list(upper))
                for name, (lower, upper) in self.signals.appearance_ranges.items()
            },
            periodic_interval_seconds=self.interval,
            note="外观线索及低频整轮时间线，不是技能身份、解除成功或按键结果判定；"
            "独立观察帧不是控制决策帧。未知、短暂、被遮挡机制可能未触发候选；"
            "时间线补充排查，受采样、内存和磁盘保留上限约束。",
        )
        try:
            self.submitted = bundle_writer.submit(
                self.directory / category,
                self.config.getint(
                    "diagnostics",
                    "scene_max_events" if self.events else "scene_routine_max_events",
                    fallback=100 if self.events else 10,
                ),
                metadata,
                images,
                self.done,
            )
        finally:
            self.frames.clear()
            self.recent.clear()
            self.bytes = 0
