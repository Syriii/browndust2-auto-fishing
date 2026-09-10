"""复用观察帧记录特殊场景及整轮低频时间线，独立于命中/失败结果。"""

import threading
import time
import uuid
from collections import Counter, deque
from pathlib import Path

from bd2_fishing.game.fishing.mechanics.lifecycle import AppearanceTracker
from bd2_fishing.game.fishing.pointer import PointerMotion
from bd2_fishing.game.fishing.scene_signals import SceneSignals
from bd2_fishing.infrastructure.diagnostics import bundle_writer


class SceneRecorder:
    """仅由反馈观察器状态锁内调用；编码/写盘交给通用后台写入器。"""

    MAX_FRAMES = 80
    MAX_BYTES = 12 * 1024 * 1024
    MAX_FRAME_BYTES = 6 * 1024 * 1024
    MAX_PARTS = 64

    def __init__(self, config, window, region, round_id, directory):
        self.config, self.window, self.region = config, window, region
        self.round_id, self.directory = round_id, Path(directory)
        self.signals = SceneSignals(config, window, region)
        self.motion = PointerMotion()
        self.lifecycle = AppearanceTracker()
        self.non_increasing_timestamps = 0
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
        self.scene_id = uuid.uuid4().hex
        self.part = 0
        self.last_flush_attempt = float("-inf")
        self.rejected_parts = 0

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
        if (
            self.frames
            and (len(self.frames) >= self.MAX_FRAMES or self.bytes + frame.nbytes > self.MAX_BYTES)
            and stamp - self.last_flush_attempt >= 0.5
            and self.part < self.MAX_PARTS - 1
        ):
            # 满段先非阻塞提交后台，保存已有前后文；队列过载时才退回有界淘汰。
            self.last_flush_attempt = stamp
            self._submit_part([], "capacity", final=False)
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
        if self.last_observed is not None and stamp <= self.last_observed:
            self.non_increasing_timestamps += 1
            return
        if frame.nbytes > min(self.MAX_FRAME_BYTES, self.MAX_BYTES):
            self.dropped_frames += 1
            self.drop_reasons["oversized"] += 1
            return
        signals, features = self.signals.inspect(frame)
        transitions = self._observe_lifecycle(signals, features, stamp)
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
        trigger = bool(confirmed) and (bool(new_signals) or stamp - self.last_event >= 3)
        if trigger:
            if len(self.events) < 64:
                self.events.append(
                    dict(
                        event_id=f"{self.scene_id}-{len(self.events) + 1:03d}",
                        observed_at=stamp,
                        context_start=self.recent[0][0] if self.recent else stamp,
                        context_end=stamp + 0.4,
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
        if transitions:
            # 出现/消失也保留前后图，不等 MISS；复用当前帧，编码仍交后台。
            for before in self.recent:
                self._keep(before, "candidate")
            self.burst_until = max(self.burst_until, stamp + 0.4)

    def _observe_lifecycle(self, signals, features, stamp):
        detections = [
            (kind, tuple(span))
            for kind, spans in features.get("appearance_regions", {}).items()
            for span in spans
        ]
        for name in (
            "blue_without_yellow",
            "multiple_pointer_candidates",
            "target_without_bright_pointer",
        ):
            if name in signals:
                detections.append((name, None))
        changes = self.lifecycle.observe(
            detections,
            stamp,
            observable=features.get("roi_available", False) and features.get("qte_active", False),
            shape=features.get("qte_shape", ()),
        )
        if changes:
            features["appearance_transitions"] = [
                dict(
                    instance_id=item.instance_id,
                    kind=item.kind,
                    state=item.state,
                    reason=item.end_reason,
                )
                for item in changes
            ]
        return changes

    def close(self, feedback, reason):
        if self.closed:
            return
        self.closed = True
        self.lifecycle.interrupt(self.last_observed, "observer_closed")
        if self.recent:
            self._keep(self.recent[-1], "final")
        if not self.frames and not self.dropped_frames:
            return
        try:
            self._submit_part(feedback, reason, final=True)
        finally:
            self.frames.clear()
            self.recent.clear()
            self.bytes = 0

    def _submit_part(self, feedback, reason, *, final):
        has_candidates = bool(self.events) or any(
            item.confirmed_at is not None for item in self.lifecycle.instances
        )
        category = "candidates" if has_candidates else "routine"
        images, records = {}, []
        for i, (stamp, (frame, features, kind)) in enumerate(sorted(self.frames.items())):
            filename = f"frame_{i:03d}.png"
            images[filename] = frame
            records.append(
                dict(file=filename, captured_at_monotonic=stamp, selection=kind, features=features)
            )
        locations = {record["captured_at_monotonic"]: record["file"] for record in records}
        candidates = []
        for event in self.events:
            location = event.get("evidence_location")
            if event["observed_at"] in locations:
                location = dict(part=self.part, file=locations[event["observed_at"]])
            candidates.append(
                dict(
                    event,
                    evidence_file=locations.get(event["observed_at"]),
                    evidence_location=location,
                )
            )
        metadata = dict(
            evidence_id=uuid.uuid4().hex,
            scene_id=self.scene_id,
            part=self.part,
            final_part=final,
            rejected_part_submissions=self.rejected_parts,
            round_id=self.round_id,
            event="qte_scene_observation",
            saved_at_unix=time.time(),
            capture_backend="GDI screen BitBlt (BGR)",
            evidence_region=self.region.as_tuple(),
            window_region=self.window.as_tuple(),
            control_region=self.signals.control_region.as_tuple(),
            crops=self.signals.crops,
            frames=records,
            candidates=candidates,
            attempts=list(self.attempts),
            feedback=list(feedback),
            close_reason=reason,
            dropped_frames=self.dropped_frames,
            dropped_frame_reasons=dict(self.drop_reasons),
            dropped_events=self.dropped_events,
            sample_gaps=self.sample_gaps,
            non_increasing_timestamps=self.non_increasing_timestamps,
            appearance_lifecycle=dict(
                schema_version=1,
                instances=self.lifecycle.snapshot(self.attempts),
                dropped_instances=self.lifecycle.dropped,
                limit=self.lifecycle.limit,
                attempt_context="仅关联观察区间内的按键编号，不证明按键针对该机制或导致消失",
                note="外观身份尚未分类；disappeared 仅代表连续两帧未见，不能证明解除成功。断档、遮挡、QTE结束保留 unknown。",
            ),
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
        done = threading.Event()
        self.submitted = bundle_writer.submit(
            self.directory / category,
            self.config.getint(
                "diagnostics",
                "scene_max_events" if has_candidates else "scene_routine_max_events",
                fallback=100 if has_candidates else 10,
            ),
            metadata,
            images,
            done,
        )
        if self.submitted:
            self.last_flush_attempt = float("-inf")
            self.done = done
            self.part += 1
            for event, saved in zip(self.events, candidates):
                if saved["evidence_location"] is not None:
                    event["evidence_location"] = saved["evidence_location"]
            self.frames.clear()
            self.bytes = 0
        else:
            self.rejected_parts += 1
