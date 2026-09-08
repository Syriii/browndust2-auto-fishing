"""game.islands.catalog：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Final

log = logging.getLogger(__name__)


class FishingLocation(StrEnum):
    """游戏内支持的钓鱼地点；枚举值与界面中文名称一致。"""

    YANBO_LAKE = "烟波湖"
    SHALLOW_SHORE = "浅岸"
    FROST_STRAIT = "寒霜海峡"
    ABYSS_MAW = "深渊巨口"
    ATLANTIS = "亚特兰蒂斯"


DEFAULT_LOCATION: Final[FishingLocation] = FishingLocation.YANBO_LAKE


LOCATION_MATCH_ALIASES: Final[dict[FishingLocation, tuple[str, ...]]] = {
    FishingLocation.YANBO_LAKE: ("烟波湖", "烟波"),
    FishingLocation.SHALLOW_SHORE: ("浅岸",),
    FishingLocation.FROST_STRAIT: ("寒霜海峡", "寒霜海", "寒霜"),
    FishingLocation.ABYSS_MAW: ("深渊巨口", "深渊", "巨口"),
    FishingLocation.ATLANTIS: ("亚特兰蒂斯", "亚特兰蒂", "特兰蒂斯"),
}
