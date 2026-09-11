"""航海入口的图像与文字读数；坐标统一到 945×532 客户区，不产生输入。"""

import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.perception.ocr_types import OCRBox, OCRText
from bd2_fishing.perception.tracing import ocr_log_context
from bd2_fishing.runtime.geometry import Rect

REFERENCE_SIZE = (945, 532)
ISLAND_NAMES = tuple(location.value for location in FishingLocation) + ("天空岛",)


@dataclass(frozen=True)
class IslandMarker:
    x: int
    y: int
    selected: bool


@dataclass(frozen=True)
class VoyageReading:
    page: str = "unknown"
    action: str | None = None
    action_point: tuple[int, int] | None = None
    action_bounds: tuple[int, int, int, int] | None = None
    island: str | None = None
    license_state: str = "unknown"
    recommended_level: int | None = None
    level_warning: bool | None = None
    player_level: int | None = None
    markers: tuple[IslandMarker, ...] = ()
    fish: tuple[str, ...] = ()
    texts: tuple[OCRText, ...] = field(default=(), repr=False)


def _text(value):
    return re.sub(r"\s+", "", value).replace("亞", "亚").replace("島", "岛")


def _within(item, bounds):
    if not item.box or item.score < 0.85:
        return False
    x, y, right, bottom = item.box.bounds
    left, top, end_x, end_y = bounds
    return left <= x < right <= end_x and top <= y < bottom <= end_y


def _find(items, label, bounds, *, contains=False):
    return next(
        (
            item
            for item in items
            if _within(item, bounds)
            and (label in _text(item.text) if contains else _text(item.text) == label)
        ),
        None,
    )


def _center(item):
    left, top, right, bottom = item.box.bounds
    return (left + right) // 2, (top + bottom) // 2


def island_markers(frame):
    hsv = cv2.cvtColor(frame[:470, :665], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (45, 100, 60), (85, 255, 255))
    _, _, stats, centers = cv2.connectedComponentsWithStats(mask)
    markers = []
    for (x, y, width, height, area), (cx, cy) in zip(stats[1:], centers[1:], strict=True):
        if not (5 < x and 65 < y and 18 <= width <= 70 and 18 <= height <= 65):
            continue
        if not (area > 180 and 0.65 < width / height < 1.4 and area / (width * height) > 0.3):
            continue
        # 圆标内部有浅色岛屿/锁图形；纯绿地形不是入口。
        tile = hsv[y : y + height, x : x + width]
        if cv2.countNonZero(cv2.inRange(tile, (0, 0, 185), (179, 90, 255))) < 20:
            continue
        markers.append(IslandMarker(round(cx), round(cy), bool(width >= 34 and height >= 34)))
    return tuple(markers)


def fish_unlocks(frame):
    """读取当前三行五列布局，保留空格和不确定状态；不推断鱼名或解锁条件。"""
    states = []
    for row in range(3):
        for column in range(5):
            x, y = 684 + column * 46, 168 + row * 46
            gray = cv2.cvtColor(frame[y : y + 39, x : x + 39], cv2.COLOR_BGR2GRAY)
            border = np.concatenate(
                (gray[:3].ravel(), gray[-3:].ravel(), gray[:, :3].ravel(), gray[:, -3:].ravel())
            )
            background = float(np.median(border))
            dark = int((gray < 180).sum())
            if 110 <= background <= 165 and float(gray.std()) >= 12:
                state = "locked"
            elif background >= 195 and dark >= 25:
                state = "unlocked"
            elif background >= 195 and dark == 0 and float(gray.std()) < 12:
                state = "empty"
            else:
                state = "unknown"
            states.append(state)
    return tuple(states)


def _selected_island(items, markers):
    names = {name for name in ISLAND_NAMES if _find(items, name, (680, 65, 920, 105))}
    # 锁定页面与白字天空岛标题可能无法读取，使用放大圆标下的标签交叉确认。
    for item in items:
        if not _within(item, (5, 70, 665, 465)):
            continue
        name = _text(item.text).replace("亚特兰带斯", "亚特兰蒂斯")
        if name not in ISLAND_NAMES:
            continue
        x, y = _center(item)
        if any(
            marker.selected and abs(marker.x - x) < 40 and 15 < y - marker.y < 55
            for marker in markers
        ):
            names.add(name)
    return next(iter(names)) if len(names) == 1 else None


def _dock_reading(items):
    """入口按钮必须与码头标题和信息栏同时出现。"""
    start = _find(items, "开始钓鱼", (810, 475, 925, 528))
    if (
        start
        and _find(items, "码头", (90, 5, 260, 55))
        and _find(items, "我的信息", (670, 45, 760, 85))
    ):
        level = next(
            (
                re.search(r"Lv\.?\s*(\d+)", t.text, re.I)
                for t in items
                if _within(t, (675, 72, 750, 102))
            ),
            None,
        )
        return VoyageReading(
            page="dock",
            action="start_fishing",
            action_point=_center(start),
            action_bounds=start.box.bounds,
            player_level=int(level[1]) if level else None,
            texts=items,
        )
    return None


def _confirmation_reading(items):
    """两类确认框有不同动作语义，优先于其后方地图或钓场识别。"""
    if (
        _find(items, "前往钓鱼地区", (390, 165, 565, 225))
        and _find(items, "失效", (330, 225, 625, 295), contains=True)
        and _find(items, "确认", (400, 295, 550, 345))
    ):
        names = [name for name in ISLAND_NAMES if _find(items, name, (365, 220, 590, 255))]
        confirm = _find(items, "确认", (400, 295, 550, 345))
        return VoyageReading(
            page="travel_confirmation",
            island=names[0] if len(names) == 1 else None,
            action="confirm_travel",
            action_point=_center(confirm),
            action_bounds=confirm.box.bounds,
            texts=items,
        )
    if (
        _find(items, "返回码头", (400, 165, 555, 225))
        and _find(items, "返回码头", (360, 215, 600, 260), contains=True)
        and _find(items, "取消", (350, 290, 470, 345))
        and _find(items, "确认", (470, 290, 590, 345))
    ):
        confirm = _find(items, "确认", (470, 290, 590, 345))
        return VoyageReading(
            page="return_confirmation",
            action="confirm_return",
            action_point=_center(confirm),
            action_bounds=confirm.box.bounds,
            texts=items,
        )
    return None


def parse_voyage(frame, items):
    """frame 为规范化客户区；文字框亦使用规范化坐标。"""
    items = tuple(items)
    confirmation = _confirmation_reading(items)
    if confirmation:
        return confirmation
    island = _island_reading(items)
    if island:
        return island
    dock = _dock_reading(items)
    if dock:
        return dock
    if not (
        _find(items, "选择钓鱼地区", (90, 5, 300, 55))
        and _find(items, "出现鱼种", (670, 135, 770, 170))
    ):
        words = {_text(t.text).upper() for t in items if _within(t, (330, 0, 630, 150))}
        return VoyageReading(
            page="loading" if {"FISHING", "VOYAGE"} <= words else "unknown", texts=items
        )
    return _map_reading(frame, items)


def _island_reading(items):
    change = _find(items, "更改", (165, 25, 270, 70))
    if not change or not _find(items, "使用时间", (95, 55, 220, 100)):
        return None
    names = [name for name in ISLAND_NAMES if _find(items, name, (95, 25, 250, 70))]
    return VoyageReading(
        page="island",
        # 本地名读不清不猜名字；更改只打开地图，目标岛屿仍须在地图上核对。
        island=names[0] if len(names) == 1 else None,
        action="change_island",
        action_point=_center(change),
        action_bounds=change.box.bounds,
        texts=items,
    )


def _recommendation(frame, items):
    """红色提示和 OCR 数值独立保留，读不到数字时不猜等级。"""
    recommended = next(
        (t for t in items if _within(t, (680, 85, 920, 135)) and "推荐钓鱼等级" in _text(t.text)),
        None,
    )
    match = re.search(r"等级[：:]?(\d+)$", _text(recommended.text)) if recommended else None
    warning = None
    if recommended:
        x, y, right, bottom = recommended.box.bounds
        hsv = cv2.cvtColor(frame[y:bottom, x:right], cv2.COLOR_BGR2HSV)
        red = cv2.inRange(hsv, (0, 130, 120), (10, 255, 255))
        red |= cv2.inRange(hsv, (170, 130, 120), (179, 255, 255))
        warning = cv2.countNonZero(red) >= 15
    return int(match[1]) if match else None, warning


def _map_reading(frame, items):
    markers = island_markers(frame)
    buy = _find(items, "购买进入许可证", (705, 475, 930, 528), contains=True)
    sail = _find(items, "启航", (705, 475, 930, 528))
    locked = _find(items, "未解锁", (680, 65, 920, 140))
    action = "purchase_license" if buy else "sail" if sail and not locked else None
    button = buy or (sail if action else None)
    level, warning = _recommendation(frame, items)
    return VoyageReading(
        page="map",
        action=action,
        action_point=_center(button) if button else None,
        action_bounds=button.box.bounds if button else None,
        island=_selected_island(items, markers),
        license_state="required" if buy or locked else "available" if sail else "unknown",
        recommended_level=level,
        level_warning=warning,
        markers=markers,
        fish=fish_unlocks(frame),
        texts=items,
    )


class VoyageReader:
    def __init__(self, engine):
        self.engine = engine

    def inspect(self, frame):
        if frame is None or self.engine is None:
            return VoyageReading()
        normalized = cv2.resize(frame, REFERENCE_SIZE, interpolation=cv2.INTER_AREA)
        with ocr_log_context("航海页面识别", Rect(0, 0, 945, 532), True):
            items = self.engine.detect_and_recognize(
                cv2.resize(normalized, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
            )
        scaled = []
        for item in items:
            if item.box:
                box = OCRBox(
                    tuple((round(x / 2), round(y / 2)) for x, y in item.box.points), item.box.score
                )
                scaled.append(OCRText(item.text, item.score, box))
        return parse_voyage(normalized, scaled)
