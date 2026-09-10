"""上钩超时诊断：缓存小区域原图，限频后在后台保存有界的诊断包。"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

import cv2

from bd2_fishing.infrastructure.diagnostics.retention import evidence_archive, evidence_path
from bd2_fishing.runtime.context import current_round_id, get_logger

log = get_logger(__name__)
_CAPTURE_CONTEXT = object()


class HookDiagnostics:
    def __init__(self, output_dir, *, enabled=True, interval_seconds=60, max_events=10):
        self.output_dir = Path(output_dir)
        self.enabled = enabled
        self.interval_seconds = max(0, interval_seconds)
        self.max_events = max(1, max_events)
        self._last_saved_at = float("-inf")
        self._slot = 0
        self._busy = threading.Lock()
        self._worker = None
        self.reset()

    def reset(self):
        self.valid_frames = 0
        self.none_frames = 0
        self.peak_pixels = 0
        self._peak_frame = None
        self._last_frame = None
        self._peak_at = None
        self._last_at = None

    def observe(self, frame, yellow_pixels=0):
        """复用识别循环已有的截图；只复制很小的感叹号区域，不编码、不写盘。"""
        if not self.enabled:
            return
        if frame is None:
            self.none_frames += 1
            return
        self.valid_frames += 1
        self._last_frame = frame.copy()
        self._last_at = time.time()
        if self._peak_frame is None or yellow_pixels > self.peak_pixels:
            self.peak_pixels = int(yellow_pixels)
            self._peak_frame = self._last_frame
            self._peak_at = self._last_at

    def save_timeout(
        self,
        capture,
        window_region,
        hook_region,
        lower,
        upper,
        threshold,
        location,
        *,
        context_frame=_CAPTURE_CONTEXT,
    ):
        """恢复动作之前额外截一次游戏客户区；所有编码与文件写入交给后台。"""
        now = time.monotonic()
        if not self.enabled or now - self._last_saved_at < self.interval_seconds:
            return False
        if not self._busy.acquire(blocking=False):
            return False
        try:
            context = None
            capture_error = None
            started = time.monotonic()
            try:
                frame = (
                    capture.grab(window_region)
                    if context_frame is _CAPTURE_CONTEXT
                    else context_frame
                )
                if frame is not None:
                    context = frame.copy()
            except Exception as exc:
                # 诊断截图失败不阻止原本的恢复流程，且保留此前有效的峰值帧。
                capture_error = f"{type(exc).__name__}: {exc}"
            capture_ms = (time.monotonic() - started) * 1000
            frames = {
                "peak_hook.png": self._peak_frame,
                "last_hook.png": self._last_frame,
                "timeout_game.png": context,
            }
            metadata = {
                "event": "wait_for_bite_timeout",
                "round_id": current_round_id(),
                "evidence_id": uuid.uuid4().hex,
                "saved_at_unix": time.time(),
                "location": str(location),
                "window_region": window_region.as_tuple(),
                "hook_region": hook_region.as_tuple(),
                "hsv_lower": [int(v) for v in lower],
                "hsv_upper": [int(v) for v in upper],
                "threshold": int(threshold),
                "peak_pixels": self.peak_pixels,
                "valid_frames": self.valid_frames,
                "none_frames": self.none_frames,
                "peak_at_unix": self._peak_at,
                "last_at_unix": self._last_at,
                "context_capture_ms": round(capture_ms, 3),
                "context_capture_error": capture_error,
                "context_source": "direct_capture"
                if context_frame is _CAPTURE_CONTEXT
                else "incident_capture",
                "context_available": context is not None,
                "note": "peak_hook and timeout_game are captured at different times; "
                "None frames mean no image returned, not necessarily a capture error.",
            }
            self._slot = self._slot % self.max_events + 1
            path = evidence_path(self.output_dir, "timeout")
            self._worker = threading.Thread(
                target=self._write_snapshot,
                args=(path, frames, metadata),
                name="hook-diagnostics",
                daemon=True,
            )
            self._worker.start()
            self._last_saved_at = now
            return True
        except Exception:
            self._busy.release()
            log.warning("提交上钩诊断截图失败，继续原有钓鱼流程", exc_info=True)
            return False

    def _write_snapshot(self, path, frames, metadata):
        job_log = get_logger(__name__, metadata.get("round_id"))
        try:
            peak = frames["peak_hook.png"]
            if peak is not None:
                hsv = cv2.cvtColor(peak, cv2.COLOR_BGR2HSV)
                lower, upper = metadata["hsv_lower"], metadata["hsv_upper"]
                frames["peak_mask.png"] = cv2.inRange(hsv, tuple(lower), tuple(upper))
                # 逐步放宽条件只用于诊断，绝不参与提竿决策。
                metadata["peak_filter_counts"] = {
                    "hue_only": cv2.countNonZero(
                        cv2.inRange(hsv, (lower[0], 0, 0), (upper[0], 255, 255))
                    ),
                    "hue_and_saturation": cv2.countNonZero(
                        cv2.inRange(hsv, (lower[0], lower[1], 0), (upper[0], upper[1], 255))
                    ),
                    "hue_and_value": cv2.countNonZero(
                        cv2.inRange(hsv, (lower[0], 0, lower[2]), (upper[0], 255, upper[2]))
                    ),
                    "full_hsv": cv2.countNonZero(frames["peak_mask.png"]),
                }
            metadata["images"] = [name for name, frame in frames.items() if frame is not None]
            with evidence_archive(path, self.max_events) as archive:
                for name, frame in frames.items():
                    if frame is None:
                        continue
                    ok, encoded = cv2.imencode(".png", frame)
                    if not ok:
                        raise RuntimeError(f"PNG 编码失败: {name}")
                    archive.writestr(name, encoded.tobytes())
                archive.writestr(
                    "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2)
                )
            job_log.info(
                "上钩超时诊断已保存: %s (峰值=%d，有效帧=%d，无新图=%d)",
                path,
                metadata["peak_pixels"],
                metadata["valid_frames"],
                metadata["none_frames"],
                extra={"user_message": "上钩超时截图已保存，可从异常截图入口查看。"},
            )
        except Exception:
            job_log.warning("保存上钩诊断截图失败，继续原有钓鱼流程", exc_info=True)
        finally:
            self._busy.release()
