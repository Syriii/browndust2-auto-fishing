"""仅预览和验证程序页面；不连接游戏、不发送输入、不保存配置。"""

import logging
import tkinter as tk

from bd2_fishing.infrastructure.windows import window as window
from bd2_fishing.runtime import control as run_control
from bd2_fishing.ui.window import FishingApp


def fake_session(*args, **kwargs):
    run_control.set_status("模拟任务运行中")
    logging.info("模拟任务已开始，可点击停止验证响应")
    run_control.sleep(180)


if __name__ == "__main__":
    window.enable_dpi_awareness()
    logging.basicConfig(level=logging.DEBUG)
    root = tk.Tk()
    app = FishingApp(root, fake_session, preview=True)
    logging.info("示例：等待上钩。正式运行前会自动聚焦游戏。")
    logging.warning("示例：满包且关闭自动清理时，任务会停止并提示。")
    root.after(180000, app.close)
    root.mainloop()
