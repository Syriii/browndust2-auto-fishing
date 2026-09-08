"""infrastructure.windows.capture：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from bd2_fishing.infrastructure.diagnostics import incidents
from bd2_fishing.runtime.geometry import Rect

log = logging.getLogger(__name__)


class DxCameraCapture:
    """对 dxcam 的轻量封装，统一输出 BGR 图像。"""

    def __init__(self, output_color: str = "BGR", window_region: Rect | None = None) -> None:
        self._camera = None
        self._monitor = None
        self._output_color = output_color
        if window_region is not None:
            self._select_camera(window_region)

    def _select_camera(self, region):
        from bd2_fishing.infrastructure.windows.display import create_camera_for_region

        self._camera, output = create_camera_for_region(region.as_tuple(), self._output_color)
        self._monitor = output
        logging.getLogger(__name__).info(
            ">>> 截图显示器: %s，设备=%d，输出=%d，屏幕区域=%s",
            output.name,
            output.device_idx,
            output.output_idx,
            output.bounds,
        )

    def grab(self, region: Rect | tuple[int, int, int, int]) -> np.ndarray | None:
        region = region if isinstance(region, Rect) else Rect(*region)
        if self._camera is None:
            self._select_camera(region)
        target = self._monitor.local_region(region.as_tuple())
        frame = self._camera.grab(region=target)
        if frame is None:
            return None
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        incidents.observe(frame, region)
        return frame

    def __enter__(self) -> "DxCameraCapture":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        release = getattr(self._camera, "release", None)
        if callable(release):
            release()
        else:
            stop = getattr(self._camera, "stop", None)
            if callable(stop):
                stop()
        self._camera = None
        self._monitor = None
