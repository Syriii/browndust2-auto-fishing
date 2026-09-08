"""供调用方使用的最小设备合同，不初始化任何原生资源。"""

from __future__ import annotations

from typing import Any, Protocol

from bd2_fishing.runtime.geometry import Rect


class FrameSource(Protocol):
    """现有 grab 合同：绝对坐标、BGR，None 表示本次没有新帧。"""

    def grab(self, region: Rect) -> Any | None: ...


class OCREngine(Protocol):
    def detect_and_recognize(self, image: Any) -> list: ...
    def recognize(self, image: Any) -> Any: ...
