"""game.inventory.reading：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging

from bd2_fishing.perception.text import build_normalized_ocr_candidates, has_alias_match

log = logging.getLogger(__name__)


BACKPACK_FULL_MATCH_ALIASES: tuple[str, ...] = (
    "背包已满，请清理背包",
    "背包已满请清理背包",
    "背包已满",
    "请清理背包",
    "清理背包",
)


def contains_backpack_full_text(texts: list[str]) -> bool:
    """判断 OCR 文本是否包含任一背包已满提示变体。"""
    normalized_candidates = build_normalized_ocr_candidates(texts)
    return has_alias_match(normalized_candidates, BACKPACK_FULL_MATCH_ALIASES)
