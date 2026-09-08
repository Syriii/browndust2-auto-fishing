"""仅预览和验证程序页面；不连接游戏、不发送输入、不保存配置。"""

import logging
from pathlib import Path
import sys
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app_ui import FishingApp
import run_control
import utils


def fake_session(*args, **kwargs):
    run_control.set_status("模拟任务运行中")
    logging.info("模拟任务已开始，可点击停止验证响应")
    run_control.sleep(180)


if __name__ == "__main__":
    utils.enable_dpi_awareness()
    logging.basicConfig(level=logging.DEBUG)
    root = tk.Tk()
    app = FishingApp(root, fake_session, preview=True)
    logging.info("示例：等待上钩。正式运行前会自动聚焦游戏。")
    logging.warning("示例：满包且关闭自动清理时，任务会停止并提示。")
    root.after(180000, app.close)
    root.mainloop()
