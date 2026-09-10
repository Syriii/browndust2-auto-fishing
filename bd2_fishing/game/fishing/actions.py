"""game.fishing.actions：从现有实现分离的职责模块。"""

from __future__ import annotations

from bd2_fishing.infrastructure.windows import input as pydirectinput
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime.context import get_logger

log = get_logger(__name__)


CAST_HOLD_SECONDS = 0.38


def cast_rod() -> None:
    """发送抛竿按键；游戏是否接受动作需由后续检测判断。"""
    run_control.set_status("正在抛竿")
    pydirectinput.keyDown("space")
    run_control.sleep(CAST_HOLD_SECONDS)
    pydirectinput.keyUp("space")
    log.info("已发送抛竿按键，等待游戏响应")


def recover_from_timeout(region) -> None:
    """超时或抛竿位置受阻时，向前移动、点击画面并重新发送抛竿按键。"""
    pydirectinput.keyDown("up")
    run_control.sleep(2)
    pydirectinput.keyUp("up")

    center_x, center_y = region.center
    pydirectinput.moveTo(center_x, center_y)
    run_control.sleep(0.2)
    pydirectinput.click()
    cast_rod()
