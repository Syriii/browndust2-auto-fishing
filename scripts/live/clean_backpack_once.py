"""手动集成测试：连接真实游戏窗口并执行一次完整背包清理。"""

from __future__ import annotations

import time
from pathlib import Path

from bd2_fishing.app import ocr_setup as ocr_setup
from bd2_fishing.game.inventory import actions as fishing_actions
from bd2_fishing.infrastructure import settings as settings
from bd2_fishing.infrastructure.windows import capture as capture_backend
from bd2_fishing.infrastructure.windows import window as window
from bd2_fishing.runtime import control as run_control

PROJECT_ROOT = Path(__file__).resolve().parents[2]


GAME_TITLE = "BrownDust II"


def main() -> None:
    """等待用户切回游戏后运行真实操作，不供自动化单元测试调用。"""
    window.enable_dpi_awareness()

    region = window.get_window_region(GAME_TITLE)
    if not region:
        input(">>> 程序结束，按回车键关闭")
        raise SystemExit(1)

    config = settings.read_ini()
    begin_wait_time = config.getfloat("time", "begin_fish_wait_time", fallback=3)
    print(">>> 将实际执行一次背包清理")
    print(f">>> 请切换到游戏窗口，{begin_wait_time} 秒后开始")
    time.sleep(begin_wait_time)

    ocr_context = ocr_setup.build_ocr_context(config, region)
    with (
        run_control.use_input_guard(window.WindowGuard(GAME_TITLE, region)),
        capture_backend.DxCameraCapture(output_color="BGR", window_region=region) as sct,
    ):
        fishing_actions.clear_backpack(region, config, sct, ocr_context)

    print(">>> 背包清理测试完成")


if __name__ == "__main__":
    main()
