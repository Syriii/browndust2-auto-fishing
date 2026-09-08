"""OCR 业务服务：截图识别地点、背包提示、地图按钮和换点条件。"""

import time
import logging
import run_control
from diagnostic_logging import ocr_log_context

from utils import DxCameraCapture, Rect
from ocr.ocr_utils import FishingLocation, sort_ocr_results, match_location_name, contains_backpack_full_text, normalize_ocr_text, OCRContext
from ocr.ocr_engine import RapidOCREngine, OCRText
from utils import Rect

CHANGE_LOCATION_POLL_TOTAL_SECONDS = 10
CHANGE_LOCATION_POLL_INTERVAL_SECONDS = 1.0
from logging_context import get_logger
log = get_logger(__name__)


class CastPositionBlocked(Exception):
    """游戏明确提示当前位置无法抛竿，由主流程决定恢复或停止。"""


def get_result_from_ocr(
    sct: DxCameraCapture,
    ocr_engine: RapidOCREngine | None,
    ocr_region: Rect,
    *, purpose: str = "通用识别", expected_empty: bool = False,
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
        log.log(level, "OCR 结果: 场景=%s ROI=%s 图像尺寸=%s 文本数=%d 允许无文字=%s 耗时毫秒=%.1f",
                purpose, ocr_region.as_tuple(), frame.shape, len(results), expected_empty,
                (time.monotonic() - started) * 1000)
        if results:
            log.debug("OCR 文本: 场景=%s 结果=%s", purpose, [(item.text, item.score) for item in results])
        return results
    except Exception:
        log.exception("OCR 执行失败: 场景=%s ROI=%s", purpose, ocr_region.as_tuple())
        return None


def get_result_by_keyword(sct: DxCameraCapture, ocr_engine: RapidOCREngine | None, ocr_region: Rect, keyword: str) -> OCRText | None:
    """返回文本完全等于关键词的首个 OCR 结果。"""
    results = get_result_from_ocr(sct, ocr_engine, ocr_region, purpose=f"查找按钮:{keyword}")
    
    if results is None:
        return None
    
    for item in results:
        if keyword == item.text:
            return item
    
    return None


def get_texts_from_ocr(
    sct: DxCameraCapture,
    ocr_engine: RapidOCREngine | None,
    ocr_region: Rect,
    *, purpose: str = "通用识别", expected_empty: bool = False,
) -> list[str] | None:
    """按画面从上到下、从左到右排序并提取非空文本。"""
    results = get_result_from_ocr(sct, ocr_engine, ocr_region, purpose=purpose, expected_empty=expected_empty)
    
    if results is None:
        return None
    sort_ocr_results(results)
    texts = [item.text.strip() for item in results if item.text.strip()]
    return texts


def get_change_btn_position(sct: DxCameraCapture, ocr_context: OCRContext, change_location_keyword: str) -> OCRText | None:
    """在限定时间内轮询地图的“更改”按钮位置。"""
    now = time.monotonic()
    while time.monotonic() - now < CHANGE_LOCATION_POLL_TOTAL_SECONDS:
        result = get_result_by_keyword(sct, ocr_context.engine, ocr_context.regions.location, change_location_keyword)
        if result is not None:
            return result

        run_control.sleep(CHANGE_LOCATION_POLL_INTERVAL_SECONDS)
    
    return None


def detect_location_from_ocr(sct: DxCameraCapture, ocr_context: OCRContext, auto_select_strategy: bool) -> FishingLocation | None:
    """最多采样三次地点文字，容忍短暂漏识别；不推测没有匹配到的钓场。"""
    if not ocr_context.enabled or ocr_context.engine is None or not auto_select_strategy:
        return None

    for attempt in range(1, 4):
        run_control.checkpoint()
        texts = get_texts_from_ocr(sct, ocr_context.engine, ocr_context.regions.location, purpose="钓场地点")
        matched_location = match_location_name(texts) if texts else None
        if matched_location is not None:
            log.info(">>> 已检测到地点: %s（第 %d/3 次）", matched_location, attempt)
            return matched_location
        log.warning("钓场识别未匹配（第 %d/3 次）：ROI=%s，文本=%s；%s",
                    attempt, ocr_context.regions.location.as_tuple(), texts,
                    "0.5 秒后重新截图识别" if attempt < 3 else "请在程序页面选择钓场后重新开始")
        if attempt < 3:
            run_control.sleep(0.5)
    return None


def check_backpack_if_full(sct: DxCameraCapture, ocr_context: OCRContext) -> bool:
    """复用抛竿提示 OCR 检查满包；明确无法抛竿时通知主流程恢复。"""
    if not ocr_context.enabled or ocr_context.engine is None:
        return False

    texts = get_texts_from_ocr(sct, ocr_context.engine, ocr_context.regions.backpack_full,
                             purpose="抛竿结果提示", expected_empty=True)
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


def check_if_have_keyword(sct: DxCameraCapture, ocr_context: OCRContext, keyword: str) -> bool:
    """检查地图 OCR 文本中是否包含指定关键词。"""
    if not ocr_context.enabled or ocr_context.engine is None:
        return False
    
    texts = get_texts_from_ocr(sct, ocr_context.engine, ocr_context.regions.map, purpose=f"钓场时间:{keyword}")
    if texts is None:
        log.info(">>> OCR 没有识别到任何文本")
        return False
    if any(keyword in text for text in texts):
        return True
    
    return False


def check_if_time_to_change_location(sct: DxCameraCapture, ocr_context: OCRContext) -> bool:
    """把地图时间文字中的“时”缺失作为需要刷新钓点的信号。"""
    if check_if_have_keyword(sct, ocr_context, "时"):
        return False
    
    log.info(">>> OCR 没有检测到“时”字，可能需要切换钓鱼点")
    return True
