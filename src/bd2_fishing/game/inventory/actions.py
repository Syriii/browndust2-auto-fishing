"""game.inventory.actions：从现有实现分离的职责模块。"""

from __future__ import annotations

import configparser

from bd2_fishing.game.islands.reading import detect_location_from_ocr
from bd2_fishing.game.navigation.actions import click_button
from bd2_fishing.game.observation import OCRContext
from bd2_fishing.infrastructure import settings as settings
from bd2_fishing.infrastructure.windows import input as pydirectinput
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime.context import get_logger
from bd2_fishing.runtime.geometry import Rect
from bd2_fishing.runtime.ports import FrameSource as DxCameraCapture

log = get_logger(__name__)


DEFAULT_BACKPACK_BUTTON_CLICK_INTERVAL_SECONDS = 2.0


def clear_backpack(
    region: Rect,
    config: configparser.ConfigParser,
    sct: DxCameraCapture | None = None,
    ocr_context: OCRContext | None = None,
) -> None:
    """执行背包出售流程；退出后若地点 OCR 消失则重试一次。"""
    run_control.set_status("正在清理背包")
    log.info("背包清理开始")
    button_click_interval = _click_clear_backpack_buttons(region, config)
    if not _should_retry_clear_backpack(sct, ocr_context, button_click_interval):
        return

    log.info(">>> 清理背包后未检测到钓鱼地点，再次清理背包")
    _click_clear_backpack_buttons(region, config, open_backpack=False)


def _click_clear_backpack_buttons(
    region: Rect,
    config: configparser.ConfigParser,
    *,
    open_backpack: bool = True,
) -> float:
    """按配置坐标依次点击背包按钮，并返回按钮间隔供后续验证使用。"""
    button_click_interval = config.getfloat(
        "backpack",
        "button_click_interval_seconds",
        fallback=DEFAULT_BACKPACK_BUTTON_CLICK_INTERVAL_SECONDS,
    )
    if open_backpack:
        pydirectinput.press("t")
    click_button(
        region=region,
        left_ratio=settings.read_config_float(config, "backpack", "one_click_sale_left"),
        top_ratio=settings.read_config_float(config, "backpack", "one_click_sale_top"),
        delay=button_click_interval,
    )
    click_button(
        region=region,
        left_ratio=settings.read_config_float(config, "backpack", "select_all_left"),
        top_ratio=settings.read_config_float(config, "backpack", "select_all_top"),
        delay=button_click_interval,
    )
    click_button(
        region=region,
        left_ratio=settings.read_config_float(config, "backpack", "circle_check_left"),
        top_ratio=settings.read_config_float(config, "backpack", "circle_check_top"),
        delay=button_click_interval,
    )
    click_button(
        region=region,
        left_ratio=settings.read_config_float(config, "backpack", "dialog_confirm_left"),
        top_ratio=settings.read_config_float(config, "backpack", "dialog_confirm_top"),
        delay=button_click_interval,
    )
    click_button(
        region=region,
        left_ratio=settings.read_config_float(config, "backpack", "quit_backpack_left"),
        top_ratio=settings.read_config_float(config, "backpack", "quit_backpack_top"),
        delay=button_click_interval,
    )
    return button_click_interval


def _should_retry_clear_backpack(
    sct: DxCameraCapture | None,
    ocr_context: OCRContext | None,
    check_delay: float,
) -> bool:
    """仅在 OCR 可用且退出背包后看不到地点时要求重试。"""
    if sct is None or ocr_context is None:
        return False

    if not ocr_context.enabled or ocr_context.engine is None:
        return False

    if check_delay:
        run_control.sleep(check_delay)

    return detect_location_from_ocr(sct, ocr_context, auto_select_strategy=True) is None
