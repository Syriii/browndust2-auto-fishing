"""game.navigation.actions：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging

from bd2_fishing.infrastructure.windows import input as pydirectinput
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime import geometry as geometry
from bd2_fishing.runtime.geometry import Rect

log = logging.getLogger(__name__)


def click_button(region: Rect, left_ratio: float, top_ratio: float, *, delay: float = 0) -> None:
    """把相对区域比例换算成屏幕坐标后点击。"""
    if delay:
        run_control.sleep(delay)
    pos = geometry.build_point_from_ratio(
        region,
        left_ratio=left_ratio,
        top_ratio=top_ratio,
    )
    pydirectinput.moveTo(*pos)
    pydirectinput.click()
