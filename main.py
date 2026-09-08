"""自动钓鱼主流程：检测上钩提示、选择 QTE 策略并串联每轮操作。"""

from __future__ import annotations

import configparser
import ctypes
import logging
import time
from pathlib import Path
from typing import Type

import cv2
import controlled_input as pydirectinput
import run_control

import qte_strategy as strategy
import utils
import operate
import ocr.ocr_utils as ocr_utils
import ocr.ocr_service as ocr_service
from ocr.ocr_enum import DEFAULT_LOCATION, FishingLocation
from utils import DxCameraCapture, Rect
from hook_diagnostics import HookDiagnostics

# 让 Windows 返回真实像素坐标，避免系统缩放导致截图区域和点击位置错位。
utils.enable_dpi_awareness()
GAME_TITLE = "BrownDust II"
BITE_PIXEL_THRESHOLD = 220
BITE_TIMEOUT_SECONDS = 15
DEFAULT_LOOP_SLEEP_SECONDS = 0.01

from logging_context import get_logger
log = get_logger(__name__)

QTE_STRATEGIES_MAP: dict[FishingLocation, Type[strategy.BaseQTEStrategy]] = {
    FishingLocation.YANBO_LAKE: strategy.FrostStraitQTEStrategy,
    FishingLocation.SHALLOW_SHORE: strategy.FrostStraitQTEStrategy,
    FishingLocation.FROST_STRAIT: strategy.FrostStraitQTEStrategy,
    FishingLocation.ABYSS_MAW: strategy.AbyssMawQTEStrategy,
    FishingLocation.ATLANTIS: strategy.FrostStraitQTEStrategy,
}


class FishingBot:
    """维护钓鱼循环所需状态，并协调截图、OCR、输入操作和 QTE 策略。"""

    def __init__(self, config: configparser.ConfigParser, region: Rect, ocr_context: ocr_service.OCRContext,
                 *, location=None, interactive=True) -> None:
        self.config = config
        self.manual_location = location
        self.interactive = interactive
        self.region = region
        self.ocr_context = ocr_context
        self.selected_location_name = DEFAULT_LOCATION
        self.pixel_threshold_scale = utils.build_pixel_threshold_scale(config, region)
        self.hook_pos = utils.build_region_from_config(config, "hook", region)
        self.hook_yellow_range = utils.read_hsv_range(config, "hook", "hook")
        self.begin_fish_wait_time = utils.read_config_float(config, "time", "begin_fish_wait_time")
        self.round_end_wait_time = utils.read_config_float(config, "time", "round_end_wait_time")
        self.bite_pixel_threshold = utils.scale_pixel_threshold(
            BITE_PIXEL_THRESHOLD,
            self.pixel_threshold_scale,
        )
        self.loop_sleep_seconds = config.getfloat(
            "time",
            "loop_sleep_seconds",
            fallback=DEFAULT_LOOP_SLEEP_SECONDS,
        )
        self.ocr_debug_once_on_start = config.getboolean(
            "ocr",
            "debug_once_on_start",
            fallback=True,
        )
        self.auto_select_strategy = config.getboolean(
            "ocr",
            "auto_select_strategy",
            fallback=True,
        )
        self.change_location_on_missing_time = config.getboolean(
            "ocr",
            "change_location_on_missing_time",
            fallback=False,
        )
        self.change_location_keyword = config.get("ocr", "change_location_keyword", fallback="时").strip()
        self.auto_clear_backpack = config.getboolean("backpack", "auto_clear_enabled", fallback=True)
        log.info(">>> 背包自动清理: %s", "开启" if self.auto_clear_backpack else "关闭（满包时停止）")
        self.hook_diagnostics = HookDiagnostics(
            Path(utils.get_base_path()) / "debug" / "hook_timeouts",
            enabled=config.getboolean("diagnostics", "enabled", fallback=True),
            interval_seconds=config.getfloat("diagnostics", "interval_seconds", fallback=60),
            max_events=config.getint("diagnostics", "max_events", fallback=10),
        )

        log.info(f">>> 当前游戏窗口截图尺寸: {region.width} x {region.height}")
        log.info(
            ">>> 像素阈值缩放倍率: "
            f"{self.pixel_threshold_scale.factor:.4f} "
            f"(参考窗口 {self.pixel_threshold_scale.reference_width} x "
            f"{self.pixel_threshold_scale.reference_height})"
        )
        log.info(f">>> 上钩黄色像素阈值: {BITE_PIXEL_THRESHOLD} -> {self.bite_pixel_threshold}")


    def _sleep_loop(self) -> None:
        run_control.sleep(self.loop_sleep_seconds)


    def wait_for_bite(self, sct: DxCameraCapture) -> None:
        """轮询感叹号区域，检测到足够多黄色像素后按空格进入 QTE。"""
        run_control.set_status("等待上钩")
        log.info("等待鱼上钩")
        wait_start_time = time.monotonic()
        max_yellow_pixel = 0
        position_recovery_attempts = 0
        self.hook_diagnostics.reset()

        while True:
            run_control.checkpoint()
            now = time.monotonic()
            if now - wait_start_time > BITE_TIMEOUT_SECONDS:
                log.warning(
                    ">>> 突发情况，尝试恢复钓鱼状态 (本窗口峰值黄色像素=%d，阈值=%d)",
                    max_yellow_pixel,
                    self.bite_pixel_threshold,
                )
                self.hook_diagnostics.save_timeout(
                    sct, self.region, self.hook_pos,
                    self.hook_yellow_range.lower, self.hook_yellow_range.upper,
                    self.bite_pixel_threshold, self.selected_location_name,
                )
                run_control.set_status("恢复钓鱼状态")
                operate.recover_from_timeout(self.region)
                run_control.set_status("等待上钩")
                # 恢复包含移动、点击和重新抛竿；下一窗口从动作完成后开始。
                wait_start_time = time.monotonic()
                max_yellow_pixel = 0
                self.hook_diagnostics.reset()
                continue

            # 复用抛竿后的提示区域检查满包及明确的抛竿失败，无需额外截图或 OCR。
            try:
                backpack_full = now - wait_start_time < 0.5 and ocr_service.check_backpack_if_full(sct, self.ocr_context)
            except ocr_service.CastPositionBlocked:
                if position_recovery_attempts >= 1:
                    reason = "自动移动并重抛后仍无法抛竿；请手动调整至船边后重新开始"
                    log.warning("%s；本轮位置恢复次数=%d", reason, position_recovery_attempts)
                    raise run_control.RunStopped(reason)
                position_recovery_attempts += 1
                run_control.set_status("调整抛竿位置")
                log.warning("抛竿位置恢复 1/1：向前移动 2 秒、点击游戏画面并重新抛竿")
                operate.recover_from_timeout(self.region)
                run_control.set_status("等待上钩")
                wait_start_time = time.monotonic()
                max_yellow_pixel = 0
                self.hook_diagnostics.reset()
                log.info("位置恢复动作已发送，重新检查抛竿提示并等待上钩")
                continue
            if backpack_full:
                if not self.auto_clear_backpack:
                    log.warning(">>> 背包已满，自动清理已关闭；请手动整理后点击开始钓鱼 重新开始")
                    raise run_control.RunStopped("背包已满，自动清理已关闭；请手动整理后重新开始")
                operate.clear_backpack(self.region, self.config, sct, self.ocr_context)
                operate.cast_rod()
                run_control.set_status("等待上钩")
                wait_start_time = time.monotonic()
                max_yellow_pixel = 0
                self.hook_diagnostics.reset()
                continue
                
            hook_frame = sct.grab(self.hook_pos)
            if hook_frame is None:
                self.hook_diagnostics.observe(None)
                self._sleep_loop()
                continue
            
            hook_hsv = cv2.cvtColor(hook_frame, cv2.COLOR_BGR2HSV)
            hook_yellow = utils.create_color_mask(
                self.hook_yellow_range.lower,
                self.hook_yellow_range.upper,
                hook_hsv,
                is_dilate=False,
            )

            hook_yellow_pixel = cv2.countNonZero(hook_yellow)
            self.hook_diagnostics.observe(hook_frame, hook_yellow_pixel)
            if hook_yellow_pixel > max_yellow_pixel:
                max_yellow_pixel = hook_yellow_pixel
            bite_detected = hook_yellow_pixel > self.bite_pixel_threshold

            if bite_detected:
                log.info(
                    ">>> 鱼上钩，黄色像素=%d (阈值=%d)",
                    hook_yellow_pixel,
                    self.bite_pixel_threshold,
                )
                pydirectinput.press("space")
                return 
            self._sleep_loop()


    def choose_strategy(self, sct: DxCameraCapture) -> strategy.BaseQTEStrategy:
        """选择界面指定钓场或自动识别；控制台模式保留手动输入。"""
        if self.manual_location is not None:
            self.selected_location_name = self.manual_location
            log.info("使用手动选择的钓场：%s", self.manual_location.value)
            return QTE_STRATEGIES_MAP[self.manual_location](self.config, self.region)
        auto_selected_name = ocr_service.detect_location_from_ocr(sct, self.ocr_context, self.auto_select_strategy)
        if auto_selected_name is not None:
            strategy_class = QTE_STRATEGIES_MAP[auto_selected_name]
            self.selected_location_name = auto_selected_name
            return strategy_class(self.config, self.region)

        if not self.interactive:
            raise RuntimeError("未能自动识别钓场，请在程序页面选择钓场后重新开始")

        log.info("可选钓鱼地点: ")
        locations = list(QTE_STRATEGIES_MAP.keys())
        for idx, location in enumerate(locations, start=1):
            log.info(f"{idx}: {location.value}")

        selected_location = run_control.console_input(">>> 输入数字对应的钓鱼地点: ")
        try:
            selected_index = int(selected_location) - 1
        except ValueError:
            selected_index = -1

        if selected_index in range(len(locations)):
            selected_name = locations[selected_index]
            log.info(f">>> 你选择了: {selected_name.value}")
            self.selected_location_name = selected_name
            strategy_class = QTE_STRATEGIES_MAP[selected_name]
        else:
            log.info(">>> 选择无效，默认使用寒霜海峡策略")
            self.selected_location_name = FishingLocation.FROST_STRAIT
            strategy_class = QTE_STRATEGIES_MAP[self.selected_location_name]

        return strategy_class(self.config, self.region)

    def should_change_location(self, sct: DxCameraCapture) -> bool:
        """按配置决定是否通过时间文字缺失来触发换点。"""
        if not self.change_location_on_missing_time:
            return False
        return ocr_service.check_if_time_to_change_location(sct, self.ocr_context)

    def run(self) -> None:
        """持续执行换点检查、抛竿、上钩检测和 QTE。"""
        with run_control.use_input_guard(utils.WindowGuard(GAME_TITLE, self.region, require_foreground=True)), \
                DxCameraCapture(output_color="BGR", window_region=self.region) as sct:
            qte_strategy = self.choose_strategy(sct)
            log.info(">>> 使用策略: %s", type(qte_strategy).__name__)
            run_control.sleep(self.begin_fish_wait_time)
            while True:
                run_control.checkpoint()
                if self.should_change_location(sct):
                    operate.change_location(sct, self.ocr_context, self.selected_location_name)
                    
                from logging_context import fishing_round
                with fishing_round():
                    log.info("开始本轮钓鱼")
                    operate.cast_rod()
                    self.wait_for_bite(sct)
                    qte_strategy.catch_observer = None
                    if qte_strategy.feedback_enabled:
                        try:
                            from catch_result import CatchObserver
                            qte_strategy.catch_observer = CatchObserver(self.ocr_context.engine, self.config, self.region)
                        except Exception:
                            log.exception("整条鱼结算观察初始化失败；继续原钓鱼流程")
                    from catch_result import run_observed_qte
                    run_observed_qte(qte_strategy, sct)
                    run_control.set_status("等待下一轮")
                    catch_observer = getattr(qte_strategy, "catch_observer", None)
                    if catch_observer is None:
                        log.info("本轮 QTE 流程已退出，等待下一轮；捕获结果尚未核实")
                    run_control.sleep(self.round_end_wait_time)


def _run_fishing_session(config=None, *, location=None, interactive=True) -> None:
    """每次启动重新定位窗口、读取配置并建立 OCR 上下文。"""
    run_control.checkpoint()
    region = utils.get_window_region(GAME_TITLE)
    if not region:
        raise RuntimeError(f"未找到标题为 '{GAME_TITLE}' 的窗口")
    log.info(">>> 已定位游戏窗口: %s", region.as_tuple())

    config = config if config is not None else utils.read_ini()
    
    ocr_context = ocr_utils.build_ocr_context(config, region)
    run_control.checkpoint()
    bot = FishingBot(config, region, ocr_context, location=location, interactive=interactive)
    try:
        bot.run()
    finally:
        worker = bot.hook_diagnostics._worker
        if worker is not None:
            worker.join(timeout=2)


def run_once(config=None, *, location=None, interactive=True) -> None:
    # 每次启动使用新线程，须在该线程初始化截图依赖的 COM 环境。
    utils.enable_dpi_awareness()
    from session_support import focus_game, keep_awake
    config = config if config is not None else utils.read_ini()
    run_control.set_status("正在聚焦游戏")
    focus_game(GAME_TITLE)
    result = ctypes.windll.ole32.CoInitializeEx(None, 2)
    if result < 0:
        raise RuntimeError(f"COM 初始化失败: {result:#x}")
    try:
        with keep_awake(config.getboolean("app", "prevent_sleep", fallback=False)):
            run_control.set_status("初始化截图与 OCR")
            _run_fishing_session(config, location=location, interactive=interactive)
    finally:
        ctypes.windll.ole32.CoUninitialize()


def main() -> None:
    import sys
    utils.setup_logging()
    utils.install_exception_hook()
    log.info(">>> 程序启动")
    from app_ui import launch
    launch(run_once, preview="--preview" in sys.argv)


if __name__ == "__main__":
    main()
