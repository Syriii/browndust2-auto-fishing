"""跨岛复用的机制目录。资料覆盖、外观候选与动作许可分别管理。"""

from dataclasses import dataclass

REVISION = "2026-09-14"


@dataclass(frozen=True)
class MechanismSpec:
    id: str
    name: str
    response: str
    coverage: str


MECHANISMS = (
    MechanismSpec("blue_lock", "蓝区锁定", "只选择实际可见且有效的黄区", "visible_targets"),
    MechanismSpec("speed", "指针加速", "使用当前可信指针；不盲目外推", "visible_targets"),
    MechanismSpec("bite", "咬人", "局部避让；主动消除规则待验证", "local_avoidance"),
    MechanismSpec("shell", "贝壳", "排除贝壳遮挡，保留其他有效目标", "local_avoidance"),
    MechanismSpec("ink", "墨汁", "仅操作可信可见目标；无定位时留证", "visibility_guard"),
    MechanismSpec("invisible", "隐形指针", "无可信指针时等待并留证", "visibility_guard"),
    MechanismSpec("freeze", "冰冻", "冰晶计数候选独立留证；尚未启用破冰输入", "observer_candidate"),
    MechanismSpec("wall", "反弹壁", "共用可达区间及普通／泡泡／绿条遮挡", "shared_range"),
    MechanismSpec("clones", "分身指针", "形状筛选后选择最亮可信指针", "visible_targets"),
    MechanismSpec("bubble", "海草泡泡球", "连续确认后每个球尝试一次；消失不等于解除", "attempt"),
    MechanismSpec("yellow_hide", "黄区消失", "连续确认无有效黄区后命中安全蓝区", "visible_targets"),
    MechanismSpec("poison", "毒海浪／反甲", "避开紫色障碍；不主动试按消除", "local_avoidance"),
    MechanismSpec("slow", "指针减速", "重新观察当前位置；无固定速度假设", "visible_targets"),
    MechanismSpec(
        "green_hold", "绿色维持区", "确认起按端才允许长按；未知端点继续留证", "pending_entry"
    ),
)
MECHANISM_IDS = frozenset(item.id for item in MECHANISMS)

# 外观不是确诊。一个线索可对应多个机制，也可能只是过渡、装饰或遮挡。
_CUE_POSSIBILITIES = {
    "wall_candidate": ("wall",),
    "freeze_counter_1": ("freeze",),
    "freeze_counter_2": ("freeze",),
    "freeze_counter_3": ("freeze",),
    "bubble_candidate": ("bubble",),
    "shell_occlusion": ("shell",),
    "red_content": ("bite",),
    "purple_content": ("poison",),
    "green_content": ("bubble", "green_hold"),
    "multiple_pointer_candidates": ("clones",),
    "target_without_bright_pointer": ("clones", "ink", "invisible"),
    "blue_without_yellow": ("yellow_hide", "ink", "shell"),
    "yellow_without_blue": ("blue_lock", "ink", "shell"),
    "no_visible_target": ("ink", "shell", "green_hold"),
}


def review_cues(cues):
    """给后台证据附检索线索；未知线索保留原值，不派发输入或断言新技能。"""
    cues = tuple(sorted(set(cues)))
    possible = sorted({item for cue in cues for item in _CUE_POSSIBILITIES.get(cue, ())})
    return dict(
        catalogue_revision=REVISION,
        possible_mechanisms=possible,
        unmapped_cues=[cue for cue in cues if cue not in _CUE_POSSIBILITIES],
        identity="unconfirmed",
        no_signature=not cues,
        # 无候选不证明普通场景：低频原图仍须留存，供未知机制复核。
    )
