"""只读检查 GDI 反馈采集与 DXcam 并行、BGR 输出及资源释放，不发送输入。"""

import ctypes
import json
import time
from ctypes import wintypes
from pathlib import Path

import cv2
import numpy as np

from bd2_fishing.infrastructure import paths
from bd2_fishing.infrastructure.windows import capture as capture_backend
from bd2_fishing.infrastructure.windows import window as window_backend
from bd2_fishing.infrastructure.windows.gdi import FeedbackCapture
from bd2_fishing.runtime import geometry as geometry

ROOT = Path(__file__).resolve().parents[2]


def main():
    window_backend.enable_dpi_awareness()
    window = window_backend.get_window_region("BrownDust II")
    if window is None:
        raise RuntimeError("未找到游戏窗口")
    region = geometry.Rect(
        window.left + round(window.width * 0.30),
        window.top + round(window.height * 0.64),
        window.left + round(window.width * 0.70),
        window.top + round(window.height * 0.93),
    )
    guard = window_backend.WindowGuard("BrownDust II", window, require_foreground=True)
    user = ctypes.WinDLL("user32")
    user.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    user.GetGuiResources.restype = wintypes.DWORD

    def handles():
        return user.GetGuiResources(wintypes.HANDLE(-1), 0)

    samples, dx_frames, peaks = [], 0, []
    output = Path(paths.get_diagnostics_path()) / (
        "feedback_capture_" + time.strftime("%Y%m%d_%H%M%S")
    )
    output.mkdir(parents=True)
    guard()
    with capture_backend.DxCameraCapture(window_region=window) as dx:
        before = handles()
        for session in range(3):
            with FeedbackCapture(region) as gdi:
                peaks.append(handles())
                for i in range(10):
                    guard()
                    start = time.perf_counter()
                    frame = gdi.grab()
                    samples.append((time.perf_counter() - start) * 1000)
                    assert frame.shape == (region.height, region.width, 3)
                    assert frame.std() > 1, "GDI 图片近乎纯色"
                    other = dx.grab(region)
                    if other is not None:
                        dx_frames += 1
                        if session == 0 and i == 0:
                            cv2.imwrite(str(output / "gdi.png"), frame)
                            cv2.imwrite(str(output / "dxcam.png"), other)
                    time.sleep(0.025)
            assert handles() <= before, "GDI 对象未全部释放"
        after = handles()
    assert dx_frames > 0, "DXcam 未产生并行帧"
    result = dict(
        region=region.as_tuple(),
        frames=len(samples),
        dx_frames=dx_frames,
        gdi_handles_before=before,
        gdi_handles_after=after,
        handles_during=peaks,
        grab_median_ms=float(np.median(samples)),
        grab_p95_ms=float(np.percentile(samples, 95)),
    )
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(output)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
