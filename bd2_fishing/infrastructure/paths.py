"""项目源码、用户运行数据和包资源使用独立路径。"""

from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[2]
    return candidate if (candidate / "pyproject.toml").is_file() else None


def get_base_path() -> str:
    """配置目录：源码 .local，普通安装用户目录，便携版 EXE 旁。"""
    if getattr(sys, "frozen", False):
        directory = Path(sys.executable).parent
    else:
        root = project_root()
        directory = root / ".local" if root is not None else Path.home() / "BD2_AutoFishing"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


def get_log_path() -> str:
    directory = Path(get_base_path())
    if not getattr(sys, "frozen", False):
        directory /= "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


def get_diagnostics_path() -> str:
    name = "diagnostics"
    directory = Path(get_base_path()) / name
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


def get_resource_path(relative_path: str) -> str:
    """自定义 OCR 资源仍相对仓库/冻结资源目录，不跟随配置迁移。"""
    if hasattr(sys, "_MEIPASS"):
        root = Path(sys._MEIPASS)
    else:
        root = project_root() or Path(get_base_path())
    return str(root / relative_path)
