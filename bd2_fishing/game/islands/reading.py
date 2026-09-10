"""game.islands.reading：从现有实现分离的职责模块。"""

from __future__ import annotations

import time

from bd2_fishing.game.islands.catalog import LOCATION_MATCH_ALIASES, FishingLocation
from bd2_fishing.game.observation import OCRContext
from bd2_fishing.perception.ocr import get_result_by_keyword, get_texts_from_ocr
from bd2_fishing.perception.ocr_types import OCRText
from bd2_fishing.perception.text import build_normalized_ocr_candidates, has_alias_match
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime.context import get_logger
from bd2_fishing.runtime.ports import FrameSource as DxCameraCapture

log = get_logger(__name__)


CHANGE_LOCATION_POLL_TOTAL_SECONDS = 10


CHANGE_LOCATION_POLL_INTERVAL_SECONDS = 1.0


def get_change_btn_position(
    sct: DxCameraCapture, ocr_context: OCRContext, change_location_keyword: str
) -> OCRText | None:
    """在限定时间内轮询地图的“更改”按钮位置。"""
    now = time.monotonic()
    while time.monotonic() - now < CHANGE_LOCATION_POLL_TOTAL_SECONDS:
        result = get_result_by_keyword(
            sct, ocr_context.engine, ocr_context.regions.location, change_location_keyword
        )
        if result is not None:
            return result

        run_control.sleep(CHANGE_LOCATION_POLL_INTERVAL_SECONDS)

    return None


def detect_location_from_ocr(
    sct: DxCameraCapture, ocr_context: OCRContext, auto_select_strategy: bool
) -> FishingLocation | None:
    """最多采样三次地点文字，容忍短暂漏识别；不推测没有匹配到的钓场。"""
    if not ocr_context.enabled or ocr_context.engine is None or not auto_select_strategy:
        return None

    for attempt in range(1, 4):
        run_control.checkpoint()
        texts = get_texts_from_ocr(
            sct, ocr_context.engine, ocr_context.regions.location, purpose="钓场地点"
        )
        matched_location = match_location_name(texts) if texts else None
        if matched_location is not None:
            log.info("当前钓场：%s", matched_location.value)
            log.debug("钓场识别成功：第 %d/3 次", attempt)
            return matched_location
        log.warning(
            "钓场识别未匹配（第 %d/3 次）：ROI=%s，文本=%s；%s",
            attempt,
            ocr_context.regions.location.as_tuple(),
            texts,
            "0.5 秒后重新截图识别" if attempt < 3 else "请在程序页面选择钓场后重新开始",
            extra={
                "user_message": f"钓场暂未识别，正在重试（{attempt}/3）。"
                if attempt < 3
                else "未能识别钓场，请在左侧选择钓场后重新开始。"
            },
        )
        if attempt < 3:
            run_control.sleep(0.5)
    return None


def check_if_have_keyword(sct: DxCameraCapture, ocr_context: OCRContext, keyword: str) -> bool:
    """检查地图 OCR 文本中是否包含指定关键词。"""
    if not ocr_context.enabled or ocr_context.engine is None:
        return False

    texts = get_texts_from_ocr(
        sct, ocr_context.engine, ocr_context.regions.map, purpose=f"钓场时间:{keyword}"
    )
    if texts is None:
        log.debug("OCR 没有识别到任何文本")
        return False
    if any(keyword in text for text in texts):
        return True

    return False


def check_if_time_to_change_location(sct: DxCameraCapture, ocr_context: OCRContext) -> bool:
    """把地图时间文字中的“时”缺失作为需要刷新钓点的信号。"""
    if check_if_have_keyword(sct, ocr_context, "时"):
        return False

    log.debug("OCR 没有检测到“时”字，可能需要切换钓鱼点")
    return True


def match_location_name(texts: list[str]) -> FishingLocation | None:
    """把 OCR 文本按地点别名映射到地点枚举。"""
    normalized_candidates = build_normalized_ocr_candidates(texts)
    for location_name, aliases in LOCATION_MATCH_ALIASES.items():
        candidate_aliases = (location_name.value, *aliases)
        if has_alias_match(normalized_candidates, candidate_aliases):
            return location_name
    return None
