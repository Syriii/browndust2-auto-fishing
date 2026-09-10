"""OCR 文字规范化、别名匹配、阅读顺序及局部坐标转换。"""

from __future__ import annotations

import logging
import unicodedata

from bd2_fishing.runtime.geometry import Rect

log = logging.getLogger(__name__)


def normalize_ocr_text(text: str) -> str:
    """移除空白、标点和符号并统一大小写，降低界面排版对匹配的影响。"""
    normalized: list[str] = []
    for char in text:
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category.startswith("P") or category.startswith("S"):
            continue
        normalized.append(char.lower())
    return "".join(normalized)


def build_normalized_ocr_candidates(texts: list[str]) -> list[str]:
    """同时生成单段和拼接文本候选，兼容一句话被 OCR 拆成多个框。"""
    normalized_candidates: list[str] = []
    for text in texts:
        normalized_text = normalize_ocr_text(text)
        if normalized_text:
            normalized_candidates.append(normalized_text)

    merged_candidate = normalize_ocr_text("".join(texts))
    if merged_candidate:
        normalized_candidates.append(merged_candidate)

    return normalized_candidates


def has_alias_match(normalized_candidates: list[str], aliases: tuple[str, ...]) -> bool:
    """使用别名包含关系容忍 OCR 少字或文本被截断。"""
    for alias in aliases:
        normalized_alias = normalize_ocr_text(alias)
        if not normalized_alias:
            continue
        for candidate in normalized_candidates:
            if normalized_alias in candidate:
                return True
            if len(candidate) >= 2 and candidate in normalized_alias:
                return True
    return False


def sort_ocr_results(results: list) -> None:
    """按文本框的纵坐标、横坐标排序，使拼接顺序接近视觉阅读顺序。"""
    results.sort(
        key=lambda item: (
            item.box.bounds[1] if item.box is not None else 0,
            item.box.bounds[0] if item.box is not None else 0,
        )
    )


def build_pos_by_bounds(bounds, region: Rect):
    """将 OCR 局部文本框中心换算为屏幕绝对点击坐标。"""
    left, top, right, bottom = bounds

    abs_center_x = region.left + (left + right) // 2
    abs_center_y = region.top + (top + bottom) // 2

    return abs_center_x, abs_center_y
