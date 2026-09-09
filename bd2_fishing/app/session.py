"""app.session：从现有实现分离的职责模块。"""

from __future__ import annotations

import ctypes

from bd2_fishing.app import ocr_setup as ocr_setup
from bd2_fishing.app.fishing_task import FishingBot
from bd2_fishing.app.preferences import verify_window_size
from bd2_fishing.game.constants import GAME_TITLE
from bd2_fishing.infrastructure import settings as settings
from bd2_fishing.infrastructure.diagnostics import incidents
from bd2_fishing.infrastructure.windows import window as window
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime.context import get_logger

log = get_logger(__name__)


def _run_fishing_session(
    config=None, *, location=None, interactive=True, capture_factory=None
) -> None:
    """每次启动重新定位窗口、读取配置并建立 OCR 上下文。"""
    run_control.checkpoint()
    region = window.get_window_region(GAME_TITLE)
    if not region:
        raise RuntimeError(f"未找到标题为 '{GAME_TITLE}' 的窗口")
    log.info(">>> 已定位游戏窗口: %s", region.as_tuple())

    config = config if config is not None else settings.read_ini()
    verify_window_size(config, region)

    # 初始化失败也需有现场；只在窗口验证通过后截取游戏客户区。
    run_control.checkpoint()
    window.WindowGuard(GAME_TITLE, region, require_foreground=True)()
    try:
        from bd2_fishing.infrastructure.windows.gdi import FeedbackCapture

        with FeedbackCapture(region) as camera:
            incidents.observe(camera.grab(), region, "session_game")
    except Exception:
        log.warning("初始化现场截图不可用，继续初始化并保留后续有效帧", exc_info=True)

    ocr_context = ocr_setup.build_ocr_context(config, region)
    run_control.checkpoint()
    bot = FishingBot(
        config,
        region,
        ocr_context,
        location=location,
        interactive=interactive,
        capture_factory=capture_factory,
    )
    try:
        bot.run()
    finally:
        worker = bot.hook_diagnostics._worker
        if worker is not None:
            worker.join(timeout=2)


def _run_once(config=None, *, location=None, interactive=True, capture_factory=None) -> None:
    # 每次启动使用新线程，须在该线程初始化截图依赖的 COM 环境。
    window.enable_dpi_awareness()
    from bd2_fishing.infrastructure.windows.session import focus_game, keep_awake

    config = config if config is not None else settings.read_ini()
    run_control.set_status("正在聚焦游戏")
    focus_game(GAME_TITLE)
    result = ctypes.windll.ole32.CoInitializeEx(None, 2)
    if result < 0:
        raise RuntimeError(f"COM 初始化失败: {result:#x}")
    try:
        with keep_awake(config.getboolean("app", "prevent_sleep", fallback=False)):
            run_control.set_status("初始化截图与 OCR")
            _run_fishing_session(
                config, location=location, interactive=interactive, capture_factory=capture_factory
            )
    finally:
        ctypes.windll.ole32.CoUninitialize()


def run_once(config=None, *, location=None, interactive=True, capture_factory=None) -> None:
    limit = config.getint("diagnostics", "failure_max_events", fallback=100) if config else 100
    with incidents.recording_session(
        max_events=limit, context={"location": str(location)}
    ) as recorder:
        try:
            _run_once(
                config, location=location, interactive=interactive, capture_factory=capture_factory
            )
        except run_control.RunStopped as exc:
            if str(exc):
                recorder.report("task_stopped", reason=str(exc))
            raise
        except Exception:
            log.exception("任务运行异常，保存已有游戏帧和异常信息")
            raise
