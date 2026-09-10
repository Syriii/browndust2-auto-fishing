"""观察侧的多区域外观生命周期；不识别技能身份、不授权按键或推断解除成功。"""

from collections import Counter
from dataclasses import asdict, dataclass


@dataclass
class AppearanceInstance:
    instance_id: int
    kind: str
    span: tuple[int, int] | None
    first_seen: float
    last_seen: float
    observations: int = 1
    missing_frames: int = 0
    state: str = "candidate"
    confirmed_at: float | None = None
    ended_at: float | None = None
    end_reason: str | None = None


class AppearanceTracker:
    """每轮最多 256 个实例；同类多个区域独立跟踪，身份歧义显式结束为未知。"""

    def __init__(self, *, limit=256, max_gap=0.3):
        self.limit, self.max_gap = limit, max_gap
        self.instances = []
        self.active = []
        self.last_at = None
        self.shape = None
        self.dropped = 0

    @staticmethod
    def _overlaps(instance, kind, span):
        if instance.kind != kind:
            return False
        if instance.span is None or span is None:
            return instance.span is None and span is None
        return max(instance.span[0], span[0]) < min(instance.span[1], span[1])

    @staticmethod
    def _end(instance, now, reason, *, disappeared=False):
        instance.state = "disappeared" if disappeared else "unknown"
        instance.ended_at, instance.end_reason = now, reason

    def interrupt(self, now, reason):
        changed = list(self.active)
        for instance in changed:
            self._end(instance, now, reason)
        self.active = []
        return changed

    def observe(self, detections, now, *, observable=True, shape=()):
        if self.last_at is not None and now <= self.last_at:
            return []
        changed = []
        if self.last_at is not None and now - self.last_at > self.max_gap:
            changed.extend(self.interrupt(now, "observation_gap"))
        if self.shape is not None and tuple(shape) != self.shape:
            changed.extend(self.interrupt(now, "geometry_changed"))
        self.last_at, self.shape = now, tuple(shape)
        if not observable:
            return changed + self.interrupt(now, "qte_or_roi_unavailable")
        matches = [
            [item for item in self.active if self._overlaps(item, kind, span)]
            for kind, span in detections
        ]
        # 合并、分裂或交叠不能冒充稳定身份：不把旧实例的动作上下文转移给新区域。
        used = Counter(item.instance_id for group in matches for item in group)
        ambiguous = {
            item.instance_id
            for group in matches
            for item in group
            if len(group) > 1 or used[item.instance_id] > 1
        }
        for item in self.active:
            if item.instance_id in ambiguous:
                self._end(item, now, "association_ambiguous")
                changed.append(item)
        observed = set()
        for (kind, span), group in zip(detections, matches):
            valid = [item for item in group if item.instance_id not in ambiguous]
            item = valid[0] if valid else self._create(kind, span, now)
            if item is None:
                continue
            observed.add(item.instance_id)
            if valid:
                changed.extend(self._update(item, span, now))
        for item in self.active:
            if item.instance_id not in observed and item.ended_at is None:
                item.missing_frames += 1
                if item.missing_frames >= 2:
                    self._end(
                        item,
                        now,
                        "absent_in_two_observations",
                        disappeared=item.confirmed_at is not None,
                    )
                    changed.append(item)
        self.active = [item for item in self.active if item.ended_at is None]
        return changed

    def _create(self, kind, span, now):
        if len(self.instances) >= self.limit:
            self.dropped += 1
            return None
        item = AppearanceInstance(len(self.instances) + 1, kind, span, now, now)
        self.instances.append(item)
        self.active.append(item)
        return item

    @staticmethod
    def _update(item, span, now):
        # 缺失过一帧的候选重新累计确认；活动实例允许一次短暂遮挡。
        item.observations = 1 if item.missing_frames else item.observations + 1
        item.span, item.last_seen, item.missing_frames = span, now, 0
        if item.confirmed_at is None and item.observations >= 2:
            item.state, item.confirmed_at = "active", now
            return [item]
        return []

    def snapshot(self, attempts=()):
        records = []
        for item in self.instances:
            record = asdict(item)
            record["attempts_in_observed_interval"] = [
                attempt["attempt"]
                for attempt in attempts
                if item.first_seen <= attempt["pressed_at"] <= item.last_seen
            ]
            record["result"] = "unknown"
            records.append(record)
        return records
