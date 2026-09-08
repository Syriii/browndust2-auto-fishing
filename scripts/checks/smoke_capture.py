"""只读截图实机检查：不聚焦、不移动窗口、不发送游戏输入。

--simulate-stale-factory 仅清空本测试进程的旧输出缓存，退出前恢复，用于回归缓存失配。
"""

import argparse
import ctypes
import logging
import threading
import time

from bd2_fishing.infrastructure.windows import capture as capture_backend
from bd2_fishing.infrastructure.windows import window as window


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate-stale-factory", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    failures = []

    def check():
        window.enable_dpi_awareness()
        result = ctypes.windll.ole32.CoInitializeEx(None, 2)
        if result < 0:
            failures.append(RuntimeError(f"COM 初始化失败: {result}"))
            return
        factory = None
        previous = None
        try:
            import dxcam

            if args.simulate_stale_factory:
                factory = getattr(dxcam, "__factory")
                previous = factory.outputs
                factory.outputs = []
            for cycle in range(1, 4):
                region = window.get_window_region("BrownDust II")
                if region is None:
                    raise RuntimeError("未找到游戏窗口，未执行截图验证")
                with capture_backend.DxCameraCapture(window_region=region) as capture:
                    frame = None
                    for _ in range(40):
                        frame = capture.grab(region)
                        if frame is not None:
                            break
                        time.sleep(0.05)
                    if frame is None:
                        raise AssertionError("2 秒内无新图")
                    assert frame.shape == (region.height, region.width, 3), frame.shape
                    assert str(frame.dtype) == "uint8"
                    print(
                        f"PASS cycle={cycle} monitor={capture._monitor.name} region={region.as_tuple()} BGR={frame.shape}",
                        flush=True,
                    )
        except BaseException as exc:
            failures.append(exc)
        finally:
            if factory is not None:
                factory.outputs = previous
            ctypes.windll.ole32.CoUninitialize()

    worker = threading.Thread(target=check, name="capture-smoke")
    worker.start()
    worker.join()
    if failures:
        raise failures[0]


if __name__ == "__main__":
    main()
