"""本游戏的 OCR 场景区域与会话设置，由应用入口组装。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bd2_fishing.runtime.geometry import Rect
from bd2_fishing.runtime.ports import OCREngine

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OCRRegions:
    """OCR 各业务场景对应的屏幕绝对区域。"""

    location: Rect
    map: Rect
    backpack_full: Rect


@dataclass(frozen=True)
class OCRContext:
    """把 OCR 开关、引擎和区域集中传递给业务流程。"""

    enabled: bool
    engine: OCREngine | None
    regions: OCRRegions
