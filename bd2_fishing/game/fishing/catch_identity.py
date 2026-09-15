"""结算鱼名与极限尺寸的保守解析；不以个人新纪录或参考范围判 MAX。"""

import re

import cv2

from bd2_fishing.game.fishing.catalogue import find_fish, reward_name
from bd2_fishing.game.fishing.catch_marks import parse_size_marks


def identify_catch(texts, location=None):
    candidates = {}
    texts = list(texts)
    for item in texts:
        text, score = item.text.strip(), item.score
        if score < 0.90:
            continue
        name = reward_name(text)
        for fish in find_fish(name, location=location):
            candidates[fish.id] = fish
    fish = next(iter(candidates.values())) if len(candidates) == 1 else None
    return fish, parse_size_marks(texts).kind


def refine_reward_identity(engine, reward, texts, location):
    """数量字形拉低整行均分时，单读鱼名，两次局部识别一致才接受。"""
    lines = [
        t
        for t in texts
        if t.box is not None and t.score >= 0.75 and re.search(r"[×xX*]\s*[1-9]\d*\s*$", t.text)
    ]
    for line in lines[:2]:
        quantity = re.search(r"[×xX*]\s*([1-9]\d*)\s*$", line.text)
        left, top, right, bottom = line.box.bounds
        end = right - round((bottom - top) * (0.8 + 0.4 * len(quantity[1])))
        candidates = []
        for padding in (0, 2):
            crop = reward[
                max(0, top - 2) : min(reward.shape[0], bottom + 3),
                max(0, left - 1) : min(reward.shape[1], end + padding),
            ]
            if not crop.size:
                break
            text = engine.recognize(
                cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            )
            fish, _ = identify_catch([text] if text else [], location)
            candidates.append(fish)
        if len(candidates) == 2 and candidates[0] is not None and candidates[0] == candidates[1]:
            return candidates[0]
    return None


def choose_target(pending, catalogue, location, time_of_day, *, ignore_time=False):
    """先当前岛，再其他目标岛；默认按时段筛选，持续模式明确忽略时段。"""
    available = [
        catalogue[identity]
        for identity, _ in pending
        if ignore_time or catalogue[identity].availability in ("both", time_of_day)
    ]
    return next(
        (f.location for f in available if f.location == location),
        available[0].location if available else None,
    )
