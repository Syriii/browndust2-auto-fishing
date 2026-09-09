"""infrastructure.settings：从现有实现分离的职责模块。"""

from __future__ import annotations

import configparser
import logging
import math
import os
import re
from importlib.resources import files
from pathlib import Path

from bd2_fishing.infrastructure.paths import get_base_path

log = logging.getLogger(__name__)


def update_config_options(path, updates):
    """只替换界面管理的选项，保留其他配置和注释；成功后原子替换。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig") if path.exists() else DEFAULT_CONFIG_CONTENT
    for section, options in updates.items():
        match = re.search(r"(?m)^\[" + re.escape(section) + r"\]\s*$", text)
        if match is None:
            text = text.rstrip() + f"\n\n[{section}]\n"
            match = re.search(r"(?m)^\[" + re.escape(section) + r"\]\s*$", text)
        next_section = re.search(r"(?m)^\[", text[match.end() :])
        end = match.end() + next_section.start() if next_section else len(text)
        block = text[match.end() : end]
        for key, value in options.items():
            pattern = r"(?m)^\s*" + re.escape(key) + r"\s*=.*$"
            replacement = f"{key} = {value}"
            if re.search(pattern, block):
                block = re.sub(pattern, lambda _: replacement, block)
            else:
                block = block.rstrip() + "\n" + replacement + "\n"
        text = text[: match.end()] + "\n" + block.lstrip("\r\n").rstrip() + "\n\n" + text[end:]
    config = configparser.ConfigParser()
    config.read_string(text)
    temporary = path.with_suffix(".ini.tmp")
    temporary.write_text(text, encoding="utf-8-sig")
    temporary.replace(path)
    return config


def read_ini(filename: str = "config.ini") -> configparser.ConfigParser:
    """读取 ini 配置文件，不存在时自动写入默认配置。"""
    full_path = os.path.join(get_base_path(), filename)
    log.info(f">>> 正在读取配置文件路径: {full_path}")

    config = configparser.ConfigParser()
    if not os.path.exists(full_path):
        log.info(f">>> 配置文件未找到，正在生成默认配置: {full_path}")
        with open(full_path, "w", encoding="utf-8-sig") as file:
            file.write(DEFAULT_CONFIG_CONTENT)

    config.read(full_path, encoding="utf-8-sig")
    return config


def read_config_int(config: configparser.ConfigParser, section: str, key: str) -> int:
    return config.getint(section, key)


def read_config_float(config: configparser.ConfigParser, section: str, key: str) -> float:
    return config.getfloat(section, key)


def bounded_float(config, section, key, fallback, minimum, maximum):
    value = config.getfloat(section, key, fallback=fallback)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"[{section}] {key} 应在 {minimum:g}–{maximum:g} 之间")
    return value


DEFAULT_CONFIG_CONTENT = (
    files("bd2_fishing").joinpath("resources/default.ini").read_text(encoding="utf-8-sig")
)
