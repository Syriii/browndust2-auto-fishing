"""仅为 setuptools 准备本机构建目录；项目元数据统一维护在 pyproject.toml。"""

from pathlib import Path

from setuptools import setup

if __name__ == "__main__":
    (Path(__file__).resolve().parent / "build").mkdir(parents=True, exist_ok=True)
    setup(
        options={
            "egg_info": {"egg_base": "build"},
            "build": {"build_base": "build/setuptools"},
        }
    )
