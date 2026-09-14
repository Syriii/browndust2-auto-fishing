"""只读录制手动 QTE：局部原图和空格状态；不聚焦、不发送输入、不启动钓鱼。"""

import argparse
import ctypes
import json
import math
import queue
import threading
import time
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import cv2

from bd2_fishing.infrastructure import paths
from bd2_fishing.infrastructure.windows import window
from bd2_fishing.infrastructure.windows.gdi import FeedbackCapture
from bd2_fishing.runtime.geometry import Rect


class ManualArchive:
    """最多八个待写原图；达到文件预算或写盘失败即通知采集停止。"""

    def __init__(self, output, byte_limit=256 * 1024 * 1024):
        self.output = output
        self.byte_limit = byte_limit
        self.pending = queue.Queue(maxsize=8)
        self.done = threading.Event()
        self.halted = threading.Event()
        self.frames = []
        self.dropped = 0
        self.reason = None
        self.error = None
        self.worker = threading.Thread(target=self.write, name="manual-qte-writer")
        self.worker.start()

    def offer(self, frame, sample):
        try:
            self.pending.put_nowait((frame, sample))
        except queue.Full:
            self.dropped += 1

    def write(self):
        try:
            with ZipFile(self.output / "frames.zip", "x", compression=ZIP_STORED) as archive:
                size = 0
                while not self.done.is_set() or not self.pending.empty():
                    try:
                        frame, sample = self.pending.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    ok, png = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 1])
                    if not ok:
                        raise RuntimeError("PNG 编码失败")
                    # ZIP 文件头与目录也计入预算，留足每条目的空间。
                    size += png.nbytes + 256
                    if size + 1024 > self.byte_limit:
                        self.reason = "byte_limit"
                        self.halted.set()
                        return
                    name = f"frame_{sample['sequence']:05d}.png"
                    archive.writestr(name, png.tobytes())
                    self.frames.append(dict(file=name, **sample))
        except BaseException as exc:
            self.error = exc
            self.reason = "writer_error"
            self.halted.set()

    def close(self):
        self.done.set()
        self.worker.join()


def space_reader():
    """只读取空格当前高位状态；不安装钩子，不采集其他按键。"""
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user.GetAsyncKeyState.restype = ctypes.c_short
    return lambda: bool(user.GetAsyncKeyState(0x20) & 0x8000)


def record(output, region, guard, *, seconds, fps, stop_file=None):
    if not math.isfinite(seconds) or not 0 < seconds <= 300 or not 1 <= fps <= 60:
        raise ValueError("时长须在 0–300 秒内，采样率须为 1–60 FPS")
    guard()
    read_space = space_reader()
    output.mkdir(parents=True, exist_ok=False)
    writer = ManualArchive(output)
    started = time.monotonic()
    reason = "deadline"
    samples = 0
    try:
        with FeedbackCapture(region) as capture:
            while time.monotonic() - started < seconds:
                if writer.halted.is_set():
                    reason = writer.reason
                    break
                if stop_file is not None and stop_file.exists():
                    reason = "stop_file"
                    break
                guard()
                before = time.monotonic() - started
                space_before = read_space()
                frame = capture.grab()
                # 抓取期间失焦或窗口变化时，该帧不进入保存队列。
                guard()
                space_after = read_space()
                after = time.monotonic() - started
                writer.offer(
                    frame,
                    dict(
                        sequence=samples,
                        before=before,
                        after=after,
                        space_before=space_before,
                        space_after=space_after,
                    ),
                )
                samples += 1
                remaining = min(1 / fps - (after - before), seconds - after)
                if remaining > 0:
                    time.sleep(remaining)
    except BaseException as exc:
        reason = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        writer.close()
        metadata = dict(
            schema_version=1,
            mode="manual_read_only",
            region=region.as_tuple(),
            fps_requested=fps,
            seconds_requested=seconds,
            elapsed=time.monotonic() - started,
            stop_reason=writer.reason or reason,
            samples=samples,
            dropped=writer.dropped,
            unsaved=samples - len(writer.frames),
            frames=writer.frames,
            writer_error=str(writer.error) if writer.error else None,
            note="before/after 为抓取前后单调时钟秒数；空格为采样状态，可能漏掉短按，"
            "不代表游戏收到输入。帧号缺口和 unsaved 标记未保存样本；"
            "外观消失、手动操作均不自动判定机制解除或捕获成功。",
        )
        (output / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if writer.error:
        raise RuntimeError("手动采样写盘失败，见 metadata.json") from writer.error
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--start-delay", type=int, choices=range(0, 16), default=5)
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    # 倒计时只给用户切回游戏的时间；此工具从不主动聚焦窗口。
    print(f"{args.start_delay} 秒后检查游戏前台，随后只读采样；Ctrl+C 可停止。", flush=True)
    time.sleep(args.start_delay)
    window.enable_dpi_awareness()
    client = window.get_window_region("BrownDust II")
    if client is None:
        raise RuntimeError("未找到游戏窗口")
    region = Rect(
        client.left + round(client.width * 0.30),
        client.top + round(client.height * 0.64),
        client.left + round(client.width * 0.70),
        client.top + round(client.height * 0.96),
    )
    guard = window.WindowGuard("BrownDust II", client, require_foreground=True)
    output = Path(paths.get_diagnostics_path()) / f"manual_mechanisms_{time.time_ns()}"
    print(output, flush=True)
    record(output, region, guard, seconds=args.seconds, fps=args.fps, stop_file=args.stop_file)


if __name__ == "__main__":
    main()
