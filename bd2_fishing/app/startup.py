"""启动时迁移、补齐并校验用户配置；检测只读、不操作游戏。"""

import configparser
import math
import platform
import shutil
import uuid
from pathlib import Path

from bd2_fishing.app.preferences import FIELDS
from bd2_fishing.infrastructure import paths
from bd2_fishing.infrastructure.settings import DEFAULT_CONFIG_CONTENT, update_config_options
from bd2_fishing.infrastructure.updates.transaction import write_json


def prepare_configuration(path, *, legacy=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    messages = []
    if not path.exists() and legacy is not None and Path(legacy).is_file():
        shutil.copy2(legacy, path)
        messages.append("已自动导入旧版设置，原文件保留。")
    created = not path.exists()
    defaults = configparser.ConfigParser()
    defaults.read_string(DEFAULT_CONFIG_CONTENT)
    if created:
        update_config_options(path, {})
        messages.append("首次运行：已生成默认设置，正在检测本机环境。")
    config = configparser.ConfigParser()
    raw = path.read_bytes()
    try:
        config.read_string(raw.decode("utf-8-sig"))
    except (UnicodeError, configparser.Error):
        backup = path.with_name(f"config.invalid-{uuid.uuid4().hex[:8]}.ini")
        backup.write_bytes(raw)
        path.write_text(DEFAULT_CONFIG_CONTENT, encoding="utf-8-sig")
        update_config_options(path, {"backpack": {"auto_clear_enabled": "false"}})
        messages.append(
            f"配置格式损坏，原文件已备份为 {backup.name}；已恢复默认值并关闭自动清包，请检查设置。"
        )
        return dict(created=created, messages=messages, repaired=True)
    updates = {}
    invalid = []
    fields = {(field.section, field.key): field for field in FIELDS}
    for section in defaults.sections():
        for key, default in defaults.items(section):
            if not config.has_option(section, key):
                updates.setdefault(section, {})[key] = default
                continue
            try:
                _validate_value(config, section, key, default, fields.get((section, key)))
            except (ValueError, configparser.Error):
                invalid.append(f"[{section}] {key}")
                updates.setdefault(section, {})[key] = (
                    "false" if (section, key) == ("backpack", "auto_clear_enabled") else default
                )
    if invalid:
        backup = path.with_name(f"config.invalid-{uuid.uuid4().hex[:8]}.ini")
        backup.write_bytes(raw)
        messages.append(
            f"已修复 {len(invalid)} 项无效设置，原配置备份为 {backup.name}；请检查设备与时延设置。"
        )
    if updates:
        update_config_options(path, updates)
    return dict(created=created, messages=messages, repaired=bool(invalid))


def _validate_value(config, section, key, default, field):
    if section == "storage":
        minimum, maximum = (1, 3650) if key == "retention_days" else (10, 102400)
        if not minimum <= config.getint(section, key) <= maximum:
            raise ValueError(key)
    elif field is not None:
        value = config.getfloat(section, key) * field.factor
        if not math.isfinite(value) or not field.minimum <= value <= field.maximum:
            raise ValueError(key)
        if field.integer and not value.is_integer():
            raise ValueError(key)
    elif default.lower() in {"true", "false"}:
        config.getboolean(section, key)
    elif (section, key) == ("app", "window_size_mode"):
        if config.get(section, key) not in {"auto", "verify"}:
            raise ValueError(key)
    else:
        try:
            float(default)
        except ValueError:
            return
        value = config.getfloat(section, key)
        if not math.isfinite(value):
            raise ValueError(key)
        if default.lstrip("-").isdigit():
            config.getint(section, key)


def initialize_desktop(services):
    """首次运行只读检测设备；已有配置仅校验，保留有效设置与原始旧配置。"""
    root = Path(paths.get_base_path())
    candidates = (root / "config.ini", root / "BD2_AutoFishing-data/config.ini")
    legacy = next((p for p in candidates if p != services.config_path and p.is_file()), None)
    result = prepare_configuration(services.config_path, legacy=legacy)
    if result["created"]:
        environment = dict(platform=platform.platform(), machine=platform.machine())
        try:
            environment["game_window"] = services.inspect_device(measure_precision=False)
            result["messages"].append("已检测游戏窗口；默认按实际客户区自动适配。")
        except Exception as exc:
            environment["game_window_error"] = str(exc)
            result["messages"].append("暂未取得游戏窗口信息；打开游戏后可在设置中重新检测。")
        write_json(paths.get_data_path() / "environment.json", environment)
    return result
