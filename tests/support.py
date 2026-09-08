"""测试使用固定仓库路径和只读默认配置，不读取个人运行设置。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
DEFAULT_CONFIG = ROOT / "src/bd2_fishing/resources/default.ini"
