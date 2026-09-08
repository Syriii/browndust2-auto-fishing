"""只读检查 GDI 反馈采集与 DXcam 并行、BGR 输出及资源释放，不发送输入。"""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
import numpy as np
import utils
from feedback_capture import FeedbackCapture


def main():
    utils.enable_dpi_awareness()
    window = utils.get_window_region("BrownDust II")
    if window is None:
        raise RuntimeError("未找到游戏窗口")
    region = utils.Rect(window.left+round(window.width*.30), window.top+round(window.height*.64),
                        window.left+round(window.width*.70), window.top+round(window.height*.93))
    guard = utils.WindowGuard("BrownDust II", window, require_foreground=True)
    user = ctypes.WinDLL("user32")
    user.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    user.GetGuiResources.restype = wintypes.DWORD
    handles = lambda: user.GetGuiResources(wintypes.HANDLE(-1), 0)
    samples, dx_frames, peaks = [], 0, []
    output = ROOT / "debug" / ("feedback_capture_"+time.strftime("%Y%m%d_%H%M%S"))
    output.mkdir(parents=True)
    guard()
    with utils.DxCameraCapture(window_region=window) as dx:
        before = handles()
        for session in range(3):
            with FeedbackCapture(region) as gdi:
                peaks.append(handles())
                for i in range(10):
                    guard()
                    start = time.perf_counter()
                    frame = gdi.grab()
                    samples.append((time.perf_counter()-start)*1000)
                    assert frame.shape == (region.height, region.width, 3)
                    assert frame.std() > 1, "GDI 图片近乎纯色"
                    other = dx.grab(region)
                    if other is not None:
                        dx_frames += 1
                        if session == 0 and i == 0:
                            cv2.imwrite(str(output / "gdi.png"), frame)
                            cv2.imwrite(str(output / "dxcam.png"), other)
                    time.sleep(.025)
            assert handles() <= before, "GDI 对象未全部释放"
        after = handles()
    assert dx_frames > 0, "DXcam 未产生并行帧"
    result = dict(region=region.as_tuple(), frames=len(samples), dx_frames=dx_frames,
                  gdi_handles_before=before, gdi_handles_after=after, handles_during=peaks,
                  grab_median_ms=float(np.median(samples)), grab_p95_ms=float(np.percentile(samples,95)))
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(output)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
