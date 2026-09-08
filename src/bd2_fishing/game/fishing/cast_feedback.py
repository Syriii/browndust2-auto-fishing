"""game.fishing.cast_feedback：从现有实现分离的职责模块。"""

from __future__ import annotations

from bd2_fishing.game.inventory.reading import contains_backpack_full_text
from bd2_fishing.game.observation import OCRContext
from bd2_fishing.perception.ocr import get_texts_from_ocr
from bd2_fishing.perception.text import normalize_ocr_text
from bd2_fishing.runtime.context import get_logger
from bd2_fishing.runtime.ports import FrameSource as DxCameraCapture

log = get_logger(__name__)


class CastPositionBlocked(Exception):
    """游戏明确提示当前位置无法抛竿，由主流程决定恢复或停止。"""


def check_backpack_if_full(sct: DxCameraCapture, ocr_context: OCRContext) -> bool:
    """复用抛竿提示 OCR 检查满包；明确无法抛竿时通知主流程恢复。"""
    if not ocr_context.enabled or ocr_context.engine is None:
        return False

    texts = get_texts_from_ocr(
        sct,
        ocr_context.engine,
        ocr_context.regions.backpack_full,
        purpose="抛竿结果提示",
        expected_empty=True,
    )
    if not texts:
        return False

    if "当前位置无法抛竿" in normalize_ocr_text("".join(texts)):
        message = " / ".join(texts)
        log.warning("检测到抛竿位置受阻；游戏提示=%s", message)
        raise CastPositionBlocked(message)

    if not contains_backpack_full_text(texts):
        return False

    log.info(">>> 检测到“背包已满，请清理背包”提示")
    return True
