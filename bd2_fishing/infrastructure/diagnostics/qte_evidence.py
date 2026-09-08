"""infrastructure.diagnostics.qte_evidence：从现有实现分离的职责模块。"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import cv2

from bd2_fishing.infrastructure.diagnostics.retention import evidence_path, prune_evidence
from bd2_fishing.perception import image as vision
from bd2_fishing.runtime.context import current_round_id, get_logger

log = logging.getLogger(__name__)


class EvidenceWriter:
    """小 ROI 原图及同帧掩膜在后台编码；队列与磁盘槽位均有上限。"""

    def __init__(
        self,
        directory,
        config,
        region,
        window,
        max_events=10,
        capture_backend="unspecified BGR source",
        round_id=None,
    ):
        self.directory, self.config = Path(directory), config
        self.region, self.window = region, window
        self.round_id = round_id or current_round_id()
        self.log = get_logger(__name__, self.round_id)
        self.capture_backend = capture_backend
        self.max_events = max(1, max_events)
        self.queue = queue.Queue(maxsize=8)
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
                outcome, samples, decision_frame = self.queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self.save(outcome, samples, decision_frame)
            except Exception:
                self.log.exception("QTE 证据保存失败；不改变钓鱼控制")

    def save(self, outcome, samples, decision_frame=None):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = evidence_path(self.directory, "qte")
        temporary = path.with_suffix(".tmp")
        ranges = {
            name: vision.read_hsv_range(self.config, "roi", name)
            for name in ("white", "yellow", "blue")
        }
        evidence_id = uuid.uuid4().hex
        metadata = dict(
            round_id=self.round_id,
            evidence_id=evidence_id,
            outcome=asdict(outcome),
            window_region=self.window.as_tuple(),
            capture_backend=self.capture_backend,
            evidence_region=self.region.as_tuple(),
            saved_at_unix=time.time(),
            frames=[],
            hsv={
                k: dict(lower=v.lower.tolist(), upper=v.upper.tolist()) for k, v in ranges.items()
            },
            decision_frame_available=decision_frame is not None,
            note="仅 QTE 结果证据；frame_* 是独立观察帧，decision.png（若有）是该次按键的控制决策原图。各自掩膜与原图同帧，原始颜色掩膜不含策略膨胀。不含真假指针判定，不是整条鱼捕获结果。",
        )
        with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
            if decision_frame is not None:
                metadata["decision_frame"] = dict(
                    file="decision.png",
                    shape=list(decision_frame.shape),
                    captured_at_monotonic=(outcome.decision or {}).get("captured_at_monotonic"),
                    frame_region=(outcome.decision or {}).get("frame_region"),
                )
                hsv = cv2.cvtColor(decision_frame, cv2.COLOR_BGR2HSV)
                images = {"decision.png": decision_frame}
                images.update(
                    {
                        f"decision_{k}.png": cv2.inRange(hsv, v.lower, v.upper)
                        for k, v in ranges.items()
                    }
                )
                for filename, image in images.items():
                    ok, data = cv2.imencode(".png", image)
                    if not ok:
                        raise RuntimeError("QTE 决策证据 PNG 编码失败")
                    archive.writestr(filename, data.tobytes())
            for i, (stamp, frame) in enumerate(samples):
                name = f"frame_{i:02d}.png"
                metadata["frames"].append(
                    dict(
                        file=name,
                        captured_at_monotonic=stamp,
                        relative_to_press_ms=None
                        if outcome.pressed_at is None
                        else (stamp - outcome.pressed_at) * 1000,
                        relative_to_feedback_ms=(stamp - outcome.observed_at) * 1000,
                    )
                )
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                images = {name: frame}
                images.update(
                    {
                        f"frame_{i:02d}_{k}.png": cv2.inRange(hsv, v.lower, v.upper)
                        for k, v in ranges.items()
                    }
                )
                for filename, image in images.items():
                    ok, data = cv2.imencode(".png", image)
                    if not ok:
                        raise RuntimeError("QTE 证据 PNG 编码失败")
                    archive.writestr(filename, data.tobytes())
            archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        temporary.replace(path)
        prune_evidence(self.directory, self.max_events)
        self.log.debug(
            "QTE 证据已保存: %s；证据ID=%s 按键=%s 帧数=%d",
            path,
            evidence_id,
            outcome.attempt,
            len(samples),
        )

    def close(self):
        self.done.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            self.log.warning("QTE 证据仍在后台写入")
