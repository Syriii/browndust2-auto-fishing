"""可取消的 OCR 采样与结果读取，依赖设备合同而非具体引擎。"""

from __future__ import annotations

import logging
import time

from bd2_fishing.perception.ocr_types import OCRText
from bd2_fishing.perception.text import sort_ocr_results
from bd2_fishing.perception.tracing import ocr_log_context
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime.context import get_logger
from bd2_fishing.runtime.geometry import Rect
from bd2_fishing.runtime.ports import FrameSource, OCREngine

log = get_logger(__name__)


def get_result_from_ocr(
    sct: FrameSource,
    ocr_engine: OCREngine | None,
    ocr_region: Rect,
    *,
    purpose: str = "通用识别",
    expected_empty: bool = False,
) -> list[OCRText] | None:
    """截取指定区域并执行 OCR；不可用或失败时统一返回 ``None``。"""
    if ocr_engine is None:
        return None

    run_control.checkpoint()
    started = time.monotonic()
    try:
        frame = sct.grab(ocr_region)
    except Exception:
        log.exception("OCR 截图异常: 场景=%s ROI=%s", purpose, ocr_region.as_tuple())
        raise
    if frame is None:
        log.info("OCR 无新图: 场景=%s ROI=%s（不等同于截图异常）", purpose, ocr_region.as_tuple())
        return None

    try:
        with ocr_log_context(purpose, ocr_region, expected_empty):
            results = ocr_engine.detect_and_recognize(frame)
        level = logging.INFO if results or expected_empty else logging.WARNING
        log.log(
            level,
            "OCR 结果: 场景=%s ROI=%s 图像尺寸=%s 文本数=%d 允许无文字=%s 耗时毫秒=%.1f",
            purpose,
            ocr_region.as_tuple(),
            frame.shape,
            len(results),
            expected_empty,
            (time.monotonic() - started) * 1000,
        )
        if results:
            log.debug(
                "OCR 文本: 场景=%s 结果=%s", purpose, [(item.text, item.score) for item in results]
            )
        return results
    except Exception:
        log.exception("OCR 执行失败: 场景=%s ROI=%s", purpose, ocr_region.as_tuple())
        return None


def get_result_by_keyword(
    sct: FrameSource, ocr_engine: OCREngine | None, ocr_region: Rect, keyword: str
) -> OCRText | None:
    """返回文本完全等于关键词的首个 OCR 结果。"""
    results = get_result_from_ocr(sct, ocr_engine, ocr_region, purpose=f"查找按钮:{keyword}")

    if results is None:
        return None

    for item in results:
        if keyword == item.text:
            return item

    return None


def get_texts_from_ocr(
    sct: FrameSource,
    ocr_engine: OCREngine | None,
    ocr_region: Rect,
    *,
    purpose: str = "通用识别",
    expected_empty: bool = False,
) -> list[str] | None:
    """按画面从上到下、从左到右排序并提取非空文本。"""
    results = get_result_from_ocr(
        sct, ocr_engine, ocr_region, purpose=purpose, expected_empty=expected_empty
    )

    if results is None:
        return None
    sort_ocr_results(results)
    texts = [item.text.strip() for item in results if item.text.strip()]
    return texts
