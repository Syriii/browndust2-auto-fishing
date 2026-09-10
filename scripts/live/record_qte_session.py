"""有界 Python 实机采样：复用采集帧运行源码，后台保存 PNG 和按键时序。

会真实钓鱼；只用于用户授权的调试。失焦/锁屏/窗口改变或达到时限立即停止。
自动清包在本次进程内关闭；不修改配置或发布程序。
"""

from __future__ import annotations

import argparse
import configparser
import ctypes
import json
import logging
import queue
import threading
import time
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import cv2

from bd2_fishing.app import fishing_task as fishing_task
from bd2_fishing.app import session as session
from bd2_fishing.game import constants as fishing_constants
from bd2_fishing.game.islands.catalog import FishingLocation
from bd2_fishing.infrastructure import paths
from bd2_fishing.infrastructure.windows import capture as capture_backend
from bd2_fishing.infrastructure.windows import input as controlled_input
from bd2_fishing.infrastructure.windows import window as window
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime import geometry as geometry

ROOT = Path(__file__).resolve().parents[2]


class Recorder:
    def __init__(self, output, control, record_frames=True):
        self.output, self.control = output, control
        self.started = time.monotonic()
        self.events, self.frames = [], []
        self.queue = queue.Queue(maxsize=12)
        self.done = threading.Event()
        self.error = None
        self.dropped = 0
        self.writer = None
        if record_frames:
            self.writer = threading.Thread(target=self.write, name="qte-png-writer")
            self.writer.start()

    def event(self, kind, **fields):
        self.events.append(dict(t=time.monotonic() - self.started, kind=kind, **fields))

    def offer(self, frame, captured):
        try:
            self.queue.put_nowait((frame, captured - self.started, self.control.phase))
        except queue.Full:
            self.dropped += 1

    def write(self):
        try:
            with ZipFile(self.output / "frames.zip", "w", compression=ZIP_STORED) as archive:
                while not self.done.is_set() or not self.queue.empty():
                    try:
                        frame, t, phase = self.queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    start = time.monotonic()
                    ok, png = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 1])
                    if not ok:
                        raise RuntimeError("PNG 编码失败")
                    name = f"frame_{len(self.frames):05d}.png"
                    archive.writestr(name, png.tobytes())
                    self.frames.append(
                        dict(
                            file=name,
                            t=t,
                            phase=phase,
                            encode_write_ms=(time.monotonic() - start) * 1000,
                        )
                    )
        except BaseException as exc:
            self.error = exc
            self.control.stopped.set()

    def close(self):
        self.done.set()
        if self.writer is not None:
            self.writer.join(timeout=10)
        metadata = dict(
            events=self.events,
            frames=self.frames,
            dropped=self.dropped,
            error=str(self.error) if self.error else None,
            note="t 为进程单调时钟偏移；frame 时间为抓取后，press_begin/end 包括驱动等待；不是命中判定",
        )
        (self.output / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if self.writer is not None and self.writer.is_alive():
            raise RuntimeError("诊断写盘未结束")
        if self.error:
            raise RuntimeError("诊断保存失败") from self.error


class SharedCapture:
    """相机只在采集线程访问；检测和录像使用同一张不可变 BGR 帧。"""

    def __init__(self, recorder, output_color="BGR", window_region=None):
        self.recorder = recorder
        self.region = window_region
        self.frame = None
        self.sequence = self.seen = 0
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.error = None

    def __enter__(self):
        self.worker = threading.Thread(target=self.capture, name="qte-live-capture")
        self.worker.start()
        deadline = time.monotonic() + 5
        try:
            while self.frame is None:
                if self.error:
                    raise self.error
                run_control.checkpoint()
                if time.monotonic() > deadline:
                    raise RuntimeError("采样相机启动超时")
                run_control.sleep(0.02)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def capture(self):
        window.enable_dpi_awareness()
        com = ctypes.windll.ole32.CoInitializeEx(None, 2)
        try:
            if com < 0:
                raise RuntimeError(f"采集线程 COM 初始化失败: {com}")
            with (
                run_control.use_control(self.recorder.control),
                run_control.use_input_guard(
                    window.WindowGuard(
                        fishing_constants.GAME_TITLE, self.region, require_foreground=True
                    )
                ),
                capture_backend.DxCameraCapture(window_region=self.region) as camera,
            ):
                saved_at = float("-inf")
                while not self.stop.is_set():
                    run_control.checkpoint()
                    frame = camera.grab(self.region)
                    now = time.monotonic()
                    if frame is not None:
                        frame = frame.copy()
                        with self.lock:
                            self.frame = frame
                            self.sequence += 1
                        interval = 1 / 20 if self.recorder.control.phase == "QTE 进行中" else 0.25
                        if now - saved_at >= interval:
                            self.recorder.offer(frame, now)
                            saved_at = now
                    run_control.sleep(0.01)
        except BaseException as exc:
            self.error = exc
            self.recorder.control.stopped.set()
        finally:
            if com >= 0:
                ctypes.windll.ole32.CoUninitialize()

    def grab(self, region):
        run_control.checkpoint()
        if self.error:
            raise self.error
        region = region if isinstance(region, geometry.Rect) else geometry.Rect(*region)
        with self.lock:
            if self.seen == self.sequence:
                return None
            self.seen = self.sequence
            frame = self.frame
        x, y = region.left - self.region.left, region.top - self.region.top
        return frame[y : y + region.height, x : x + region.width]

    def __exit__(self, *args):
        self.stop.set()
        self.worker.join(timeout=5)


def load_debug_config(path=None):
    """默认使用源码的个人配置；其他配置必须用 --config 明确选择。"""
    if path is None:
        path = ROOT / ".local" / "config.ini"
    path = Path(path).resolve()
    config = configparser.ConfigParser()
    with path.open(encoding="utf-8-sig") as source:
        config.read_file(source)
    for section in ("backpack", "ocr", "diagnostics"):
        if not config.has_section(section):
            raise ValueError(f"调试配置缺少 [{section}]: {path}")
    return config, path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=45)
    parser.add_argument(
        "--config", type=Path, help="只读指定配置文件；工作树中可指向原目录的用户配置"
    )
    parser.add_argument(
        "--stop-file", type=Path, help="测试时创建此文件可请求正常停止并完成截图写盘"
    )
    parser.add_argument(
        "--location", choices=[v.value for v in FishingLocation], default="亚特兰蒂斯"
    )
    parser.add_argument(
        "--probe-outcomes",
        action="store_true",
        help="仅调试：分别在色条外和蓝条内按一次，采集失败与普通命中反馈",
    )
    parser.add_argument(
        "--probe-escape",
        action="store_true",
        help="仅调试：进入 QTE 后只观察、不按键，采集超时结束证据",
    )
    parser.add_argument(
        "--feedback", action="store_true", help="兼容旧命令；QTE 结果观察和失败留图现已始终启用"
    )
    parser.add_argument(
        "--no-full-frames",
        action="store_true",
        help="沿用原游戏采集路径，不录制高频全窗口画面；仍保存按键时序及已启用的失败证据",
    )
    args = parser.parse_args()
    if not 1 <= args.seconds <= 90:
        parser.error("seconds 必须为 1–90")
    if args.stop_file is not None and args.stop_file.exists():
        parser.error("停止文件已存在；请为本次测试指定新路径")
    if args.probe_outcomes and args.probe_escape:
        parser.error("两种探针不能同时启用")
    output = Path(paths.get_diagnostics_path()) / ("qte_live_" + time.strftime("%Y%m%d_%H%M%S"))
    output.mkdir(parents=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(output / "session.log", encoding="utf-8"),
        ],
    )
    logging.getLogger().handlers[0].setLevel(logging.INFO)
    logging.getLogger("bd2_fishing.game.fishing.tracing").setLevel(logging.DEBUG)
    config, config_path = load_debug_config(args.config)
    logging.info("Python 调试源码=%s；配置（只读）=%s", ROOT, config_path)
    config.set("backpack", "auto_clear_enabled", "false")
    config.set("ocr", "change_location_on_missing_time", "false")
    config.set("diagnostics", "qte_detail_log", "true")
    control = run_control.RunControl()
    recorder = Recorder(output, control, record_frames=not args.no_full_frames)
    if args.probe_outcomes:
        from bd2_fishing.game.fishing import qte as qte_strategy

        class ProbeStrategy(qte_strategy.FrostStraitQTEStrategy):
            def play_qte(self, sct):
                # 探针也需要观察器；独立结束后再进入原策略，避免嵌套启动泄漏。
                self._start_feedback()
                try:
                    run_control.sleep(0.15)
                    self._probe_feedback(sct)
                finally:
                    self._stop_feedback()
                super().play_qte(sct)

            def _probe_feedback(self, sct):
                run_control.set_status("QTE 进行中")
                for target in ("outside", "blue"):
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        run_control.checkpoint()
                        hsv = self._grab_qte_frames(sct)
                        if hsv is None:
                            self._sleep_loop()
                            continue
                        th, qh = self._split_roi_and_time(hsv)
                        if not self._time_bar_visible(th):
                            self._sleep_loop()
                            continue
                        cursor = self._find_cursor_x(qh)
                        yellow = self._yellow_mask(qh)
                        # 仅用于采样普通命中反馈，不是生产色条阈值。
                        blue = cv2.inRange(qh, (85, 70, 120), (115, 255, 255))
                        if cursor is not None:
                            on_yellow = self._mask_column_has_color(yellow, cursor)
                            on_blue = self._mask_column_has_color(blue, cursor)
                            if not on_yellow and (
                                (target == "outside" and not on_blue)
                                or (target == "blue" and on_blue)
                            ):
                                recorder.event("probe_target", target=target, cursor=cursor)
                                self._press_qte()
                                run_control.sleep(1)
                                break
                        self._sleep_loop()

        fishing_task.QTE_STRATEGIES_MAP[FishingLocation(args.location)] = ProbeStrategy
    if args.probe_escape:
        from bd2_fishing.game.fishing import qte as qte_strategy

        class ObserveEscapeStrategy(qte_strategy.FrostStraitQTEStrategy):
            @qte_strategy.trace_qte
            def play_qte(self, sct):
                started, no_bar = False, 0
                deadline = time.monotonic() + self.longest_keep_time
                recorder.event("escape_probe_begin")
                while time.monotonic() < deadline:
                    run_control.checkpoint()
                    hsv = self._grab_qte_frames(sct)
                    if hsv is not None:
                        timer, _ = self._split_roi_and_time(hsv)
                        if self._time_bar_visible(timer):
                            started, no_bar = True, 0
                        elif started:
                            no_bar += 1
                            if self._on_bar_disappeared(no_bar):
                                return
                        self._qte_trace.observe("observe_only")
                    self._sleep_loop()
                self._qte_trace.reason = "longest_keep_time"

        fishing_task.QTE_STRATEGIES_MAP[FishingLocation(args.location)] = ObserveEscapeStrategy
    capture_factory, original_press = capture_backend.DxCameraCapture, controlled_input.press

    def traced_press(*values, **kwargs):
        recorder.event("press_begin", keys=list(values), phase=control.phase)
        try:
            return original_press(*values, **kwargs)
        finally:
            recorder.event("press_end", phase=control.phase)

    if not args.no_full_frames:

        def capture_factory(**kwargs):
            return SharedCapture(recorder, **kwargs)

    controlled_input.press = traced_press

    def timeout():
        recorder.event("deadline")
        control.stop(controlled_input.release_inputs)

    timer = threading.Timer(args.seconds, timeout)
    timer.start()

    def watch_stop_file():
        while not control.stopped.wait(0.1):
            if args.stop_file.exists():
                recorder.event("external_stop")
                control.stop(controlled_input.release_inputs)
                break

    watcher = None
    if args.stop_file is not None:
        watcher = threading.Thread(target=watch_stop_file, name="qte-test-stop", daemon=True)
        watcher.start()
    try:
        with run_control.use_control(control):
            session.run_once(
                config,
                location=FishingLocation(args.location),
                interactive=False,
                capture_factory=capture_factory,
            )
    except run_control.RunStopped as exc:
        recorder.event("stopped", reason=str(exc) or "达到时限或采集保护停止")
    finally:
        timer.cancel()
        control.stop(controlled_input.release_inputs)
        if watcher is not None:
            watcher.join(timeout=1)
        controlled_input.press = original_press
        recorder.close()
        print(f"调试结束，按键已释放。输出: {output}", flush=True)


if __name__ == "__main__":
    main()
