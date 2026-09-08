"""game.fishing.settlement_rules：从现有实现分离的职责模块。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class CatchResult:
    status: str = "unknown"
    reason: str = "尚未观察到结算"
    reward: str = ""
    size_cm: float | None = None
    remaining_cm: float | None = None


def distance_value(text):
    normalized = re.sub(r"\s+", "", text).upper().replace("O", "0")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)CM", normalized)
    return float(match.group(1)) if match else None


def _evidence_token(text):
    quantity = re.search(r"[×xX*]\s*([1-9]\d*)", text)
    if quantity:
        return "quantity", int(quantity.group(1))
    distance = distance_value(text)
    return ("distance", distance) if distance is not None else None


def classify_settlement(panel_open, reward_texts, timer_values, distance_texts):
    """仅使用本轮的明确奖励或超时证据，空画面不表示失败。"""
    reliable = [t.text for t in reward_texts if t.score >= 0.75]
    rewards = [t for t in reliable if re.search(r"[×xX*]\s*[1-9]\d*", t)]
    sizes = [distance_value(t) for t in reliable]
    sizes = [value for value in sizes if value is not None and value > 0]
    if panel_open and rewards and sizes:
        return CatchResult("caught", "结算关闭提示与鱼奖励数量、尺寸同时出现", rewards[0], sizes[0])
    if panel_open:
        return CatchResult("unknown", "结算面板已出现，但奖励文字未完整识别")
    if rewards and sizes:
        return CatchResult("unknown", "看到奖励文字，但关闭提示未确认；不能判为逃脱")
    distances = [distance_value(t.text) for t in distance_texts if t.score >= 0.80]
    distances = [value for value in distances if value is not None]
    # 录像中计时器从 1 直接消失，未观察到 0；因此不冒充游戏明确宣告逃脱。
    tail = timer_values[-3:]
    exhausted = (len(timer_values) >= 2 and all(value <= 1 for value in timer_values[-2:])) or (
        len(tail) == 3 and tail[-1] <= 1 and tail[0] <= 2 and tail[0] >= tail[1] >= tail[2]
    )
    if exhausted and distances and distances[-1] > 0:
        return CatchResult(
            "suspected_escape",
            "倒计时接近耗尽、距离仍大于零，QTE 随后退出；未见奖励面板",
            remaining_cm=distances[-1],
        )
    return CatchResult("unknown", "QTE 已退出，但缺少可确认的整条鱼结算证据")
