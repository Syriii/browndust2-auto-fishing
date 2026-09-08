"""infrastructure.diagnostics.logging：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from bd2_fishing.infrastructure.diagnostics.buffered_logging import BufferedHandler
from bd2_fishing.infrastructure.paths import get_log_path

log = logging.getLogger(__name__)


_fault_file = None


def setup_logging() -> None:
    """初始化日志，写入程序目录下的日志文件并输出到控制台。"""
    root_logger = logging.getLogger()
    if any(getattr(handler, "_bd2_file", False) for handler in root_logger.handlers):
        return
    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        os.path.join(get_log_path(), "auto_fishing.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    buffered_file = BufferedHandler(file_handler)
    buffered_file._bd2_file = True
    root_logger.addHandler(buffered_file)

    if sys.stderr is not None and not any(
        isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        for handler in root_logger.handlers
    ):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # 原生崩溃（如 onnxruntime / dxcam 段错误）时把 Python 调用栈转储到文件。
    try:
        import faulthandler

        global _fault_file

        _fault_file = open(
            os.path.join(get_log_path(), "auto_fishing.fault.log"),
            "a",
            encoding="utf-8",
        )
        faulthandler.enable(file=_fault_file)
    except Exception as exc:
        logging.getLogger(__name__).warning("faulthandler 初始化失败: %s", exc)


def install_exception_hook() -> None:
    """捕获未处理异常写入日志，并在打包环境下保持控制台窗口不立即关闭。"""
    logger = logging.getLogger(__name__)

    def handle_uncaught(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("未捕获的异常", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        if getattr(sys, "frozen", False):
            try:
                input(">>> 程序异常退出，详细信息已写入 auto_fishing.log，按回车键关闭")
            except Exception:
                pass

    sys.excepthook = handle_uncaught
