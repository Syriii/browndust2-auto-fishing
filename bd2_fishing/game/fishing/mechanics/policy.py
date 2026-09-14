"""同帧机制仲裁：只返回一个动作意图，由 QTE 执行层调用设备。

时间由调用者传入；不截图、不等待、不写日志。动作许可不等于游戏处理成功。
"""

from dataclasses import dataclass
from typing import Literal

from bd2_fishing.game.fishing.mechanics.blue_target import BlueTarget
from bd2_fishing.game.fishing.mechanics.bubble_memory import BubbleMemory
from bd2_fishing.game.fishing.mechanics.bubble_targets import BubbleTargets
from bd2_fishing.game.fishing.mechanics.green_control import GreenHoldController
from bd2_fishing.game.fishing.mechanics.regions import MechanismRegions
from bd2_fishing.game.fishing.mechanics.yellow_aim import YellowAim
from bd2_fishing.game.fishing.mechanics.yellow_geometry import YellowTargetMemory
from bd2_fishing.game.fishing.trigger_rules import TargetEntryTrigger


@dataclass(frozen=True)
class MechanismDecision:
    action: Literal["normal", "wait", "press", "down", "up"]
    reason: str
    started_at: float | None = None
    bubble_span: tuple[int, int] | None = None


class TargetPolicy:
    """所有钓场共用黄区优先、蓝区连续确认与同次入区去重。"""

    def __init__(self):
        self.trigger = TargetEntryTrigger()
        self.blue_confirmations = 0
        self.yellow_aim = YellowAim()
        self.yellow_geometry = YellowTargetMemory()

    def invalidate(self):
        # 无图、无光标、遮挡或专用动作不证明离开普通目标。
        self.blue_confirmations = 0
        self.yellow_aim.reset()
        self.yellow_geometry.reset()

    def suspend_for_green(self):
        self.invalidate()
        self.trigger.armed, self.trigger.target = True, None

    def observe(
        self,
        *,
        yellow_present,
        yellow_overlap=None,
        blue: BlueTarget | None = None,
        blocked=False,
    ):
        if blocked:
            self.invalidate()
            return None
        if yellow_present:
            self.blue_confirmations = 0
            target, overlap = "yellow", yellow_overlap
        else:
            self.yellow_geometry.reset()
            self.yellow_aim.reset()
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
        self.bubble = BubbleTargets()
        self.bubble_memory = BubbleMemory()
        self.regions = None
        self.targets = TargetPolicy()

    def observe(self, regions: MechanismRegions, cursor, now):
        normalized = self.bubble_memory.normalize(regions, now)
        if not self.green.held:
            regions = normalized
        self.regions = regions
        blocked = cursor is not None and bool(regions.blocked[cursor])
        green = self.green.observe(
            regions.green, cursor, now, present=regions.green_present, blocked=blocked
        )
        if green.action != "normal":
            return self._green_step(regions, green, cursor, now, blocked)
        if self.bubble.observe(regions.bubble_spans, cursor, now, blocked=blocked):
            self.targets.invalidate()
            return MechanismDecision("press", "bubble_target", bubble_span=self.bubble.span)
        return MechanismDecision("normal", "ordinary_targets")

    def _green_step(self, regions, green, cursor, now, blocked):
        separate = self._separate_bubbles(regions, green)
        if self.bubble.observe(
            separate, cursor if separate else None, now, blocked=blocked, uncertain=True
        ):
            self.targets.invalidate()
            return MechanismDecision("press", "bubble_target", bubble_span=self.bubble.span)
        # 真实像素已给出位置时，起按端未知只限制该区域；长按/松键仍独占输入。
        if (
            green.action == "wait"
            and not self.green.held
            and regions.green_present
            and regions.green_spans
            and cursor is not None
        ):
            ordinary = regions.with_green_exclusion()
            if not ordinary.blocked[cursor]:
                self.regions = ordinary
                return MechanismDecision("normal", "green_spatially_separate")
        if green.action in ("down", "up") or self.green.held:
            self.targets.suspend_for_green()
        else:
            # 绿色候选遮挡不等于离开黄/蓝条，不能借此重新授权同次入区。
            self.targets.invalidate()
        return MechanismDecision(green.action, green.reason, green.started_at)

    def _separate_bubbles(self, regions, green):
        if self.green.held or green.action != "wait" or regions.green is None:
            return ()
        target = regions.green
        return tuple(
            (left, right)
            for left, right in regions.bubble_spans
            if right <= target.left or left >= target.right
        )

    def invalidate_observation(self):
        self.bubble_memory = BubbleMemory()
        self.targets.invalidate()
        self.bubble.invalidate_observation()
        if self.green.held:
            green = self.green.release("green_frame_unavailable")
            return MechanismDecision(green.action, green.reason, green.started_at)
        self.green.invalidate_observation()
        return MechanismDecision("wait", "frame_unavailable")
