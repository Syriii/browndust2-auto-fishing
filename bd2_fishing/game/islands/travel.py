"""刷新钓场的往返策略；每段实际导航交给页面识别与动作协调器。"""

from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.game.navigation.voyage import NavigationFailed, prepare_voyage
from bd2_fishing.runtime import control
from bd2_fishing.runtime.context import get_logger

log = get_logger(__name__)


class LocationChangeFailed(RuntimeError):
    """往返未完成，不能继续使用原钓场策略抛竿。"""


def change_location(config, region, ocr_context, current_location):
    """烟波湖经浅岸中转，其余已支持钓场经烟波湖中转；确认返回才算完成。"""
    control.checkpoint()
    try:
        origin = FishingLocation(current_location)
    except (ValueError, TypeError) as exc:
        raise LocationChangeFailed("未确认原钓场，无法选择刷新路线。") from exc
    if not ocr_context.enabled or ocr_context.engine is None:
        raise LocationChangeFailed("换点需要文字识别，当前 OCR 不可用，未执行换点。")
    if not config.getboolean("navigation", "confirm_island_change", fallback=True):
        raise LocationChangeFailed("自动确认换岛已关闭，未执行自动往返换点。")
    transit = (
        FishingLocation.SHALLOW_SHORE
        if origin == FishingLocation.YANBO_LAKE
        else FishingLocation.YANBO_LAKE
    )
    for destination in (transit, origin):
        control.checkpoint()
        log.info("刷新钓场：前往%s。", destination)
        try:
            arrived = prepare_voyage(
                config, region, ocr_context.engine, destination, change_from_island=True
            )
        except NavigationFailed as exc:
            raise LocationChangeFailed(f"刷新钓场时未能到达{destination}：{exc}") from exc
        if arrived != destination:
            raise LocationChangeFailed(f"未确认到达{destination}，已停止后续换点和抛竿。")
    log.info("已返回%s，钓场往返完成。", origin)
