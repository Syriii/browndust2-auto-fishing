"""设备与性能设置的展示、校验及运行前窗口约束。"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SettingField:
    section: str
    key: str
    label: str
    minimum: float
    maximum: float
    factor: float = 1
    integer: bool = False


FIELDS = (
    SettingField("time", "loop_sleep_seconds", "QTE 检测间隔（毫秒）", 1, 100, 1000),
    SettingField("time", "qte_hold_seconds", "QTE 按住时间（毫秒）", 5, 500, 1000),
    SettingField("time", "qte_settle_seconds", "QTE 松开后等待（毫秒）", 0, 1000, 1000),
    SettingField("time", "feedback_poll_seconds", "反馈观察间隔（毫秒）", 5, 200, 1000),
    SettingField("time", "begin_fish_wait_time", "开始前等待（秒）", 0, 60),
    SettingField("time", "fish_end_wait_time", "结算等待（秒）", 0, 30),
    SettingField("time", "round_end_wait_time", "轮次间等待（秒）", 0, 60),
    SettingField("time", "longest_keep_time", "QTE 超时上限（秒）", 5, 180, integer=True),
    SettingField("app", "expected_window_width", "预期客户区宽度（像素）", 320, 7680, integer=True),
    SettingField(
        "app", "expected_window_height", "预期客户区高度（像素）", 180, 4320, integer=True
    ),
)


def form_values(config, defaults):
    values = {}
    for field in FIELDS:
        value = config.getfloat(
            field.section, field.key, fallback=defaults.getfloat(field.section, field.key)
        )
        values[field.key] = f"{value * field.factor:g}"
    values["window_size_mode"] = config.get("app", "window_size_mode", fallback="auto")
    return values


def validate_form(values):
    updates = {}
    for field in FIELDS:
        try:
            number = float(values[field.key])
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"{field.label}：请输入数值") from exc
        if (
            not math.isfinite(number)
            or not field.minimum <= number <= field.maximum
            or (field.integer and not number.is_integer())
        ):
            raise ValueError(f"{field.label}：范围 {field.minimum:g}–{field.maximum:g}")
        updates.setdefault(field.section, {})[field.key] = f"{number / field.factor:g}"
    mode = values.get("window_size_mode")
    if mode not in ("auto", "verify"):
        raise ValueError("请选择自动适配或校验指定尺寸")
    updates.setdefault("app", {})["window_size_mode"] = mode
    return updates


def verify_window_size(config, region):
    mode = config.get("app", "window_size_mode", fallback="auto")
    if mode not in ("auto", "verify"):
        raise ValueError("窗口适配模式必须为 auto 或 verify")
    if mode == "verify":
        expected = (
            config.getint("app", "expected_window_width"),
            config.getint("app", "expected_window_height"),
        )
        if expected != (region.width, region.height):
            raise ValueError(
                f"游戏客户区为 {region.width}×{region.height}，设置要求 {expected[0]}×{expected[1]}；"
                "请调整游戏窗口，或在设备与时延设置中选择自动适配"
            )
