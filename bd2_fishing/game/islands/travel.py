"""game.islands.travel：从现有实现分离的职责模块。"""

from __future__ import annotations

import time

from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.game.islands.reading import check_if_have_keyword, get_change_btn_position
from bd2_fishing.game.navigation.actions import click_button
from bd2_fishing.game.observation import OCRContext
from bd2_fishing.infrastructure.windows import input as pydirectinput
from bd2_fishing.perception.text import build_pos_by_bounds
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime.context import get_logger
from bd2_fishing.runtime.ports import FrameSource as DxCameraCapture

log = get_logger(__name__)


CHANGE_LOCATION_POLL_DELAY_SECONDS = 5.0


CHANGE_LOCATION_POLL_TOTAL_SECONDS = 10


CHANGE_LOCATION_BTN_NAME = "更改"


class LocationChangeFailed(RuntimeError):
    """未能确认返回钓鱼页面，调用方必须停止后续游戏动作。"""


MAP_TRANSITIONS = {
    FishingLocation.YANBO_LAKE: [
        {"name": FishingLocation.SHALLOW_SHORE, "position": (0.39, 0.53)},
        {"name": FishingLocation.FROST_STRAIT, "position": (0.29, 0.30)},
        {"name": FishingLocation.ABYSS_MAW, "position": (0.01, 0.48)},
        {"name": FishingLocation.ATLANTIS, "position": (0.01, 0.48)},
    ],
    FishingLocation.SHALLOW_SHORE: [{"name": FishingLocation.YANBO_LAKE, "position": (0.41, 0.79)}],
    FishingLocation.FROST_STRAIT: [{"name": FishingLocation.YANBO_LAKE, "position": (0.48, 0.79)}],
    FishingLocation.ABYSS_MAW: [{"name": FishingLocation.YANBO_LAKE, "position": (0.60, 0.79)}],
    FishingLocation.ATLANTIS: [{"name": FishingLocation.YANBO_LAKE, "position": (0.60, 0.79)}],
}


def click_change_btn(sct: DxCameraCapture, ocr_context: OCRContext) -> None:
    """点击 OCR 识别到的“更改”按钮，识别失败时使用已知兜底坐标。"""
    btn_ocr_result = get_change_btn_position(
        sct, ocr_context, change_location_keyword=CHANGE_LOCATION_BTN_NAME
    )
    if btn_ocr_result is None or btn_ocr_result.box is None:
        # 按钮文字偶尔会被动画遮挡，兜底坐标仍位于固定的“更改”按钮区域。
        click_button(region=ocr_context.regions.map, left_ratio=0.21, top_ratio=0.10, delay=0.5)
    else:
        change_btn_pos = build_pos_by_bounds(
            btn_ocr_result.box.bounds, ocr_context.regions.location
        )
        pydirectinput.moveTo(*change_btn_pos)
        pydirectinput.click()


def change_location(
    sct: DxCameraCapture, ocr_context: OCRContext, current_location: FishingLocation
) -> None:
    """先前往中转钓点，再按反向路径回到当前钓点以刷新鱼群。"""
    log.info(">>> 切换钓点")

    # 先从当前地点前往中转点，让原地点在返回时重新加载。
    click_change_btn(sct, ocr_context)

    # 每个钓点的第一条边指向中转点，当前地图结构以烟波湖为中心。
    temp_map = MAP_TRANSITIONS.get(current_location, [])[0]

    temp_ratio = temp_map["position"]
    temp_name = temp_map["name"]
    click_button(
        region=ocr_context.regions.map, left_ratio=temp_ratio[0], top_ratio=temp_ratio[1], delay=2
    )

    click_button(region=ocr_context.regions.map, left_ratio=0.85, top_ratio=0.95, delay=0.5)

    click_button(region=ocr_context.regions.map, left_ratio=0.50, top_ratio=0.58, delay=1)

    # 到达中转点后重新打开地图，沿反向边回到原地点。
    run_control.sleep(CHANGE_LOCATION_POLL_DELAY_SECONDS)
    click_change_btn(sct, ocr_context)

    # 从临时地图继续查找回目标地点的路径并点击
    for next_map in MAP_TRANSITIONS.get(temp_name, []):
        if next_map.get("name") != current_location:
            continue

        next_ratio = next_map["position"]
        click_button(
            region=ocr_context.regions.map,
            left_ratio=next_ratio[0],
            top_ratio=next_ratio[1],
            delay=0.5,
        )
        break

    click_button(region=ocr_context.regions.map, left_ratio=0.85, top_ratio=0.95, delay=0.5)

    click_button(region=ocr_context.regions.map, left_ratio=0.50, top_ratio=0.58, delay=1)

    # “更改”按钮重新出现表示航行动画结束且地图界面恢复可操作。
    run_control.sleep(CHANGE_LOCATION_POLL_DELAY_SECONDS)
    now = time.monotonic()
    while time.monotonic() - now < CHANGE_LOCATION_POLL_TOTAL_SECONDS:
        run_control.checkpoint()
        if check_if_have_keyword(sct, ocr_context, CHANGE_LOCATION_BTN_NAME):
            log.info(">>> 已成功切换地点")
            return
        run_control.sleep(0.2)
    raise LocationChangeFailed("换岛后未能确认钓鱼页面已恢复；请检查游戏页面后重新开始")
