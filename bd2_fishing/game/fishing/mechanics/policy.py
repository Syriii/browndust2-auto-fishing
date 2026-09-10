"""同帧机制仲裁：只返回一个动作意图，由 QTE 执行层调用设备。

时间由调用者传入；不截图、不等待、不写日志。动作许可不等于游戏处理成功。
"""

from dataclasses import dataclass
from typing import Literal

from bd2_fishing.game.fishing.mechanics.blue_target import BlueTarget
from bd2_fishing.game.fishing.mechanics.bubbles import BubbleController
from bd2_fishing.game.fishing.mechanics.green_control import GreenHoldController
from bd2_fishing.game.fishing.mechanics.regions import MechanismRegions
from bd2_fishing.game.fishing.trigger_rules import TargetEntryTrigger


@dataclass(frozen=True)
class MechanismDecision:
    action: Literal["normal", "wait", "press", "down", "up"]
    reason: str
    started_at: float | None = None
    bubble_span: tuple[int, int] | None = None


class TargetPolicy:
    """黄区优先、蓝区连续确认与同次入区去重，两套地点策略共用。"""

    def __init__(self):
        self.trigger = TargetEntryTrigger()
        self.blue_confirmations = 0

    def invalidate(self):
        # 无图、无光标、遮挡或专用动作不证明离开普通目标。
        self.blue_confirmations = 0

    def suspend_for_green(self):
        self.invalidate()
        self.trigger.armed, self.trigger.target = True, None

    def observe(
        self, *, yellow_present, yellow_overlap=None, blue: BlueTarget | None = None, blocked=False
    ):
        if blocked:
            self.invalidate()
            return None
        if yellow_present:
            self.invalidate()
            target, overlap = "yellow", yellow_overlap
        else:
            self.blue_confirmations = (
                min(2, self.blue_confirmations + 1) if blue is not None and blue.safe_spans else 0
            )
            target = "blue"
            overlap = blue.overlap if self.blue_confirmations >= 2 else None
        return target if self.trigger.observe(overlap, target) else None


class MechanismPolicy:
    """每轮拥有绿条、泡泡和普通目标状态；已有优先级保持不变。"""

    def __init__(self):
        self.green = GreenHoldController()
        self.bubble = BubbleController()
        self.targets = TargetPolicy()

    def observe(self, regions: MechanismRegions, cursor, now):
        blocked = cursor is not None and bool(regions.blocked[cursor])
        green = self.green.observe(
            regions.green, cursor, now, present=regions.green_present, blocked=blocked
        )
        if green.action != "normal":
            self.bubble.observe((), None, now, uncertain=True)
            self.targets.suspend_for_green()
            return MechanismDecision(green.action, green.reason, green.started_at)
        if self.bubble.observe(regions.bubble_spans, cursor, now, blocked=blocked):
            self.targets.invalidate()
            return MechanismDecision("press", "bubble_target", bubble_span=self.bubble.span)
        return MechanismDecision("normal", "ordinary_targets")

    def invalidate_observation(self):
        self.targets.invalidate()
        self.bubble.invalidate_observation()
        if self.green.held:
            green = self.green.release("green_frame_unavailable")
            return MechanismDecision(green.action, green.reason, green.started_at)
        self.green.invalidate_observation()
        return MechanismDecision("wait", "frame_unavailable")
