"""有时限的真实游戏实测；失去游戏焦点时停止，结束后释放脚本按键。"""

from __future__ import annotations

import argparse
import builtins
import functools
import time
from pathlib import Path

import pydirectinput
import win32gui

from bd2_fishing.app import fishing_task as fishing_task
from bd2_fishing.app import ocr_setup
from bd2_fishing.game import constants as fishing_constants
from bd2_fishing.infrastructure import settings
from bd2_fishing.infrastructure.diagnostics import logging as logging_setup
from bd2_fishing.infrastructure.windows import input as controlled_input
from bd2_fishing.infrastructure.windows import window

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class StopLiveTest(Exception):
    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=90)
    parser.add_argument("--location", type=int, choices=range(1, 6), default=4)
    parser.add_argument(
        "--hook-upper-hue",
        type=int,
        choices=range(181),
        default=None,
        help="仅本次实测覆盖上钩色相上限，不修改 config.ini",
    )
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")

    logging_setup.setup_logging()
    region = window.get_window_region(fishing_constants.GAME_TITLE)
    if region is None:
        raise SystemExit("未找到游戏窗口")
    hwnd = win32gui.FindWindow(None, fishing_constants.GAME_TITLE)
    print(f">>> 实测窗口: {region.as_tuple()}", flush=True)
    config = settings.read_ini()
    if args.hook_upper_hue is not None:
        config.set("hook", "hook_upper_hue", str(args.hook_upper_hue))
        print(f">>> 本次实测临时设置 hook_upper_hue={args.hook_upper_hue}", flush=True)
    context = ocr_setup.build_ocr_context(config, region)
    bot = fishing_task.FishingBot(config, region, context)
    print(">>> 8 秒后开始真实游戏实测，请切回游戏。测试期间切走焦点会停止。", flush=True)
    time.sleep(8)
    if win32gui.GetForegroundWindow() != hwnd:
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception as exc:
            raise SystemExit(f"无法聚焦游戏，请先切回游戏再运行: {exc}")

    deadline = time.monotonic() + args.seconds
    original_sleep, original_input = time.sleep, builtins.input
    action_names = ("press", "keyDown", "moveTo", "click")
    originals = {name: getattr(controlled_input, name) for name in action_names}

    def check():
        if time.monotonic() >= deadline:
            raise StopLiveTest("达到实测时限")
        if win32gui.GetForegroundWindow() != hwnd:
            raise StopLiveTest("游戏失去焦点")

    def checked_sleep(seconds):
        end = time.monotonic() + seconds
        while True:
            check()
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            original_sleep(min(remaining, 0.05))

    def guarded(action):
        @functools.wraps(action)
        def wrapped(*values, **options):
            check()
            return action(*values, **options)

        return wrapped

    def select_location(prompt=""):
        if "钓鱼地点" not in prompt:
            raise StopLiveTest(f"需要人工输入: {prompt}")
        print(f"{prompt}{args.location}（实测指定的备用地点）", flush=True)
        return str(args.location)

    try:
        time.sleep = checked_sleep
        builtins.input = select_location
        for name, action in originals.items():
            setattr(controlled_input, name, guarded(action))
        bot.run()
    except (StopLiveTest, KeyboardInterrupt) as exc:
        print(f">>> 实测停止: {exc}", flush=True)
    finally:
        time.sleep, builtins.input = original_sleep, original_input
        for name, action in originals.items():
            setattr(controlled_input, name, action)
        previous_failsafe = pydirectinput.FAILSAFE
        try:
            pydirectinput.FAILSAFE = False
            pydirectinput.keyUp("space", _pause=False)
            pydirectinput.keyUp("up", _pause=False)
        finally:
            pydirectinput.FAILSAFE = previous_failsafe
        worker = bot.hook_diagnostics._worker
        if worker is not None:
            worker.join(timeout=5)
        print(">>> 实测结束，脚本按键已释放", flush=True)


if __name__ == "__main__":
    main()
