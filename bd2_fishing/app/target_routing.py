"""只在抛竿前调度待办；换岛沿用已确认的地图导航。"""

from bd2_fishing.game.fishing.catch_identity import choose_target
from bd2_fishing.game.fishing.daytime import read_daytime
from bd2_fishing.game.fishing.settlement import confirm_ready_for_next_cast
from bd2_fishing.game.islands.reading import detect_location_from_ocr
from bd2_fishing.game.navigation.voyage import prepare_voyage
from bd2_fishing.infrastructure.windows import window
from bd2_fishing.runtime import control
from bd2_fishing.runtime.context import get_logger

log = get_logger(__name__)


def _waiting_status(pending, catalogue, daytime):
    names = "、".join(dict.fromkeys(catalogue[i].name for i, _ in pending))
    if daytime == "unknown":
        return f"等待确认游戏时段 · {names}"
    needed = {catalogue[i].availability for i, _ in pending}
    wait = "等待白天" if needed == {"day"} else "等待夜晚"
    current = "白天" if daytime == "day" else "夜晚"
    return f"{wait} · {names}（当前{current}）"


def prepare_target_cast(bot, capture):
    collection = bot.collection
    guard = window.WindowGuard("BrownDust II", bot.region, require_foreground=True)
    last_wait = None
    while True:
        control.checkpoint()
        guard()
        if collection.completed:
            raise control.RunStopped("所有目标已完成，鱼获已保存")
        actual = detect_location_from_ocr(capture, bot.ocr_context, True)
        if actual is None:
            control.set_status("等待确认当前钓场")
            control.sleep(3)
            continue
        bot.selected_location_name = actual
        # 两次新帧确认时段；过渡、遮挡与单帧闪光不能授权限定时段抛竿。
        daytime = "unknown"
        if collection.wait_for_time:
            first = read_daytime(capture.grab(bot.region))
            control.sleep(0.2)
            guard()
            second = read_daytime(capture.grab(bot.region))
            daytime = first if first == second else "unknown"
        pending = collection.journal.targets()
        destination = choose_target(
            pending, collection.catalogue, actual, daytime, ignore_time=not collection.wait_for_time
        )
        if destination is None:
            status = _waiting_status(pending, collection.catalogue, daytime)
            control.set_status(status)
            if status != last_wait:
                log.info("目标尚未满足抛竿条件：%s", status)
                last_wait = status
            control.sleep(3)
            continue
        if last_wait is not None:
            log.info("目标时段已满足，继续确认钓场与抛竿条件。")
            last_wait = None
        if destination != actual:
            control.set_status(f"前往{destination.value}")
            arrived = prepare_voyage(
                bot.config, bot.region, bot.ocr_context.engine, destination, change_from_island=True
            )
            if arrived != destination:
                raise control.RunStopped("尚未确认到达目标钓场，请检查游戏页面")
            bot.manual_location = destination
            bot.selected_location_name = destination
            confirm_ready_for_next_cast(bot.config, bot.region)
            continue  # 航行后重读时段，不能沿用起航前的时间。
        confirm_ready_for_next_cast(bot.config, bot.region)
        return
