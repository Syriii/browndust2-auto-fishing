"""game.fishing.settlement：从现有实现分离的职责模块。"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from bd2_fishing.game.fishing.settlement_rules import (
    CatchResult,
    _evidence_token,
    classify_settlement,
    distance_value,
)
from bd2_fishing.game.fishing.tracing import QTEControlTimeout
from bd2_fishing.infrastructure import paths as paths
from bd2_fishing.infrastructure.diagnostics import bundle_writer
from bd2_fishing.infrastructure.windows import window as window
from bd2_fishing.infrastructure.windows.gdi import FeedbackCapture
from bd2_fishing.perception.ocr_types import OCRText
from bd2_fishing.runtime import control as run_control
from bd2_fishing.runtime.context import current_round_id, get_logger

log = get_logger(__name__)


def read_settlement_texts(engine, image):
    """对小字的低置信度数量/尺寸放大复核；只接受两次读数一致的关键值。"""
    results = engine.detect_and_recognize(image)
    checked = []
    for item in results:
        token = _evidence_token(item.text)
        if item.score < 0.85 and item.box is not None and token is not None:
            left, top, right, bottom = item.box.bounds
            crop = image[
                max(0, top - 1) : min(image.shape[0], bottom + 2),
                max(0, left - 1) : min(image.shape[1], right + 2),
            ]
            if crop.size:
                refined = engine.recognize(
                    cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                )
                if (
                    refined is not None
                    and refined.score >= 0.85
                    and _evidence_token(refined.text) == token
                ):
                    item = OCRText(refined.text, refined.score, item.box)
            if item.score < 0.75 and token[0] == "quantity":
                # 生僻鱼名会拉低整行均分；单独读行尾“×数量”，不伪造未读准的鱼名。
                tail_left = max(
                    left, right - round((bottom - top) * (1 + len(str(token[1])) * 0.5))
                )
                tail = image[
                    max(0, top - 1) : min(image.shape[0], bottom + 2),
                    max(0, tail_left) : min(image.shape[1], right + 2),
                ]
                if tail.size:
                    refined = engine.recognize(
                        cv2.resize(tail, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                    )
                    if (
                        refined is not None
                        and refined.score >= 0.80
                        and re.fullmatch(r"[×xX*]\s*[1-9]\d*", refined.text.strip())
                        and _evidence_token(refined.text) == token
                    ):
                        item = OCRText("×" + str(token[1]), refined.score, item.box)
        checked.append(item)
    return checked


class CatchObserver:
    def __init__(self, engine, config, window):
        self.round_id = current_round_id() or uuid.uuid4().hex[:12]
        self.log = get_logger(__name__, self.round_id)
        self.engine, self.config, self.window = engine, config, window
        self.lock = threading.Lock()
        self.ocr_lock = threading.Lock()
        self.readings = deque(maxlen=32)
        self.next_timer_at = 0.0
        self.settling = False
        self.result = CatchResult()
        self.game_feedback = []
        self.attempt_outcomes = []
        self.feedback_diagnostics = {}
        self.last_frame = None
        self.last_frame_at = None
        self.evidence_frames = {}
        self.evidence_metadata = {}
        self.finalized = False
        self.save_done = threading.Event()
        self.save_done.set()
        close_template = cv2.imdecode(
            np.frombuffer(
                (Path(__file__).with_name("assets") / "settlement_close.png").read_bytes(), np.uint8
            ),
            cv2.IMREAD_GRAYSCALE,
        )
        # 关闭提示是灰字。先套亮白阈值再匹配会把缩放后的模板清空，
        # TM_CCOEFF_NORMED 对常量模板返回 1，导致任意场景都被判为面板。
        if close_template is None or close_template.std() < 1:
            raise ValueError("结算关闭提示模板无有效字形")
        width = round(close_template.shape[1] * window.width / 875)
        height = round(close_template.shape[0] * window.height / 492)
        # 字体栅格化取整与整张图的缩放并不完全一致，限定 ±1 像素搜索。
        self.close_patterns = [
            cv2.resize(close_template, (max(2, width + dx), max(2, height + dy)))
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
        ]

    def observe_timer(self, frame, stamp):
        if not self.ocr_lock.acquire(blocking=False):
            return
        try:
            with self.lock:
                if self.settling or stamp < self.next_timer_at:
                    return
                self.next_timer_at = stamp + 0.25
                # 即使倒计时 OCR 失败，也保留本轮最后一张只读截图。
                self.last_frame, self.last_frame_at = frame.copy(), stamp
            # frame 为原反馈 ROI（客户区 x=30%..70%, y=64%..93%）。
            x1, x2 = round(self.window.width * 0.022), round(self.window.width * 0.070)
            y1, y2 = round(self.window.height * 0.183), round(self.window.height * 0.238)
            timer = frame[y1:y2, x1:x2]
            value = self.engine.recognize(timer)
            if (
                value is not None
                and value.score >= 0.90
                and re.fullmatch(r"\d{1,2}", value.text.strip())
            ):
                with self.lock:
                    if not self.settling:
                        self.readings.append(
                            (stamp, int(value.text.strip()), frame.copy(), value.score)
                        )
        except Exception:
            if not self.settling:
                self.log.warning("结算计时器观察失败，保留现场供维护", exc_info=True)
        finally:
            self.ocr_lock.release()

    def stop_observing(self):
        """封存观察状态；原生 OCR 迟到返回不能再修改本轮数据。"""
        with self.lock:
            self.settling = True

    @contextmanager
    def _settlement_ocr(self):
        # 不与后台 OCR 并发调用同一引擎，等待时仍检查取消与窗口保护。
        deadline = time.monotonic() + 2
        while not self.ocr_lock.acquire(blocking=False):
            run_control.checkpoint()
            if time.monotonic() >= deadline:
                raise TimeoutError("后台计时器 OCR 未结束，结算保持未确认")
            run_control.sleep(0.02)
        try:
            yield
        finally:
            self.ocr_lock.release()

    def _panel_open(self, frame):
        roi = frame[
            round(self.window.height * 0.88) : round(self.window.height * 0.97),
            round(self.window.width * 0.40) : round(self.window.width * 0.60),
        ]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        for pattern in self.close_patterns:
            if pattern.std() < 1 or any(a < b for a, b in zip(gray.shape, pattern.shape)):
                continue
            score = cv2.minMaxLoc(cv2.matchTemplate(gray, pattern, cv2.TM_CCOEFF_NORMED))[1]
            if score >= 0.85:
                return True
        return False

    def finish(self):
        """QTE 确认退出后、关闭面板前执行；耗时从原结算等待时间中扣除。"""
        self.stop_observing()
        run_control.checkpoint()
        guard = window.WindowGuard("BrownDust II", self.window, require_foreground=True)
        budget = min(4.0, max(0.0, self.config.getfloat("time", "fish_end_wait_time", fallback=4)))
        deadline = time.monotonic() + budget
        frame, captured, panel = None, None, False
        self.evidence_metadata["panel_open"] = False
        samples = []
        with FeedbackCapture(self.window) as capture:
            # 同时限制次数与时间；逐次响应取消/窗口保护，只保留首帧与最新帧。
            for _ in range(21):
                run_control.checkpoint()
                guard()
                candidate = capture.grab()
                stamp = time.monotonic()
                if candidate is not None:
                    frame, captured = candidate, stamp
                    panel = self._panel_open(frame)
                    if "settlement_first.png" not in self.evidence_frames:
                        self.evidence_frames["settlement_first.png"] = frame.copy()
                        self.evidence_metadata["first_settlement_at_monotonic"] = stamp
                    self.evidence_frames["settlement.png"] = frame.copy()
                    self.evidence_metadata.update(captured_at_monotonic=stamp, panel_open=panel)
                samples.append(
                    dict(
                        captured_at_monotonic=stamp,
                        frame_available=candidate is not None,
                        panel_open=panel if candidate is not None else False,
                    )
                )
                self.evidence_metadata["settlement_wait_samples"] = samples
                if panel or stamp >= deadline:
                    break
                run_control.sleep(min(0.2, max(0, deadline - stamp)))
        if frame is None:
            raise RuntimeError("结算等待期间未取得有效截图")
        with self._settlement_ocr():
            readings = list(self.readings)
            reward_texts, distance_texts = [], []
            distance_reading = None
            if panel:
                reward = frame[
                    round(self.window.height * 0.08) : round(self.window.height * 0.21),
                    round(self.window.width * 0.36) : round(self.window.width * 0.65),
                ]
                reward_texts = read_settlement_texts(self.engine, reward)
            elif readings and captured - readings[-1][0] <= 4:
                # 最后一帧可能被 FAIL/拳头等特效遮住；有限回看，并保留距离所用的同帧图。
                for reading in list(reversed(readings))[:5:2]:
                    if captured - reading[0] > 4:
                        continue
                    distance_reading = reading
                    distance = reading[2][
                        round(self.window.height * 0.120) : round(self.window.height * 0.170),
                        round(self.window.width * 0.078) :,
                    ]
                    distance_texts = read_settlement_texts(self.engine, distance)
                    run_control.checkpoint()
                    if any(
                        t.score >= 0.80 and distance_value(t.text) is not None
                        for t in distance_texts
                    ):
                        break
            run_control.checkpoint()
            recent = [value for stamp, value, _, _ in readings if captured - stamp <= 4]
            if (
                not panel
                and recent
                and recent[-1] <= 1
                and any(
                    t.score >= 0.80 and distance_value(t.text) is not None for t in distance_texts
                )
            ):
                # 关闭提示可能被特效/动画漏识别；先排除实际已有鱼奖励的场景。
                reward = frame[
                    round(self.window.height * 0.08) : round(self.window.height * 0.21),
                    round(self.window.width * 0.36) : round(self.window.width * 0.65),
                ]
                reward_texts = read_settlement_texts(self.engine, reward)
                run_control.checkpoint()
            self.result = classify_settlement(panel, reward_texts, recent, distance_texts)
        labels = {"caught": "确认捕获", "suspected_escape": "疑似超时逃脱", "unknown": "未确认"}
        self.log.debug(
            "结算观察依据: 结果=%s 原因=%s 奖励=%s 尺寸cm=%s 剩余cm=%s",
            labels[self.result.status],
            self.result.reason,
            self.result.reward,
            self.result.size_cm,
            self.result.remaining_cm,
        )
        self.evidence_metadata = dict(
            self.evidence_metadata,
            captured_at_monotonic=captured,
            window_region=self.window.as_tuple(),
            panel_open=panel,
            timer_readings=[dict(time=t, value=v, score=s) for t, v, _, s in readings],
            reward_texts=[asdict(t) for t in reward_texts],
            distance_texts=[asdict(t) for t in distance_texts],
            distance_frame_at=None if distance_reading is None else distance_reading[0],
            note="success: explicit reward; suspected_escape: visual inference, not explicit game failure",
        )
        if readings:
            self.evidence_frames["last_timer_qte.png"] = readings[-1][2]
        if distance_reading is not None:
            self.evidence_frames["distance_qte.png"] = distance_reading[2]

    def finalize(self, reason):
        """观察线程关闭后落盘完整账本；这里只使用缓存，停止后不截图或 OCR。"""
        if self.finalized:
            return
        self.finalized = True
        self.stop_observing()
        if reason == "interrupted":
            self.mark_interrupted()
        elif self.result.reason == "尚未观察到结算":
            self.result = CatchResult(
                "unknown",
                "QTE 控制超时，未确认退出页面，任务停止"
                if reason == "control_timeout"
                else "QTE 已返回，但未观察到结算"
                if reason == "returned"
                else f"QTE 异常退出：{reason}",
            )
        frames = dict(self.evidence_frames)
        if self.last_frame is not None:
            frames["last_observed_qte.png"] = self.last_frame
        metadata = dict(
            self.evidence_metadata,
            round_id=self.round_id,
            evidence_id=uuid.uuid4().hex,
            result=asdict(self.result),
            exit_reason=reason,
            finalized_at_monotonic=time.monotonic(),
            window_region=self.window.as_tuple(),
            last_observed_at_monotonic=self.last_frame_at,
            game_feedback=list(self.game_feedback),
            attempt_outcomes=list(self.attempt_outcomes),
            feedback_diagnostics=dict(self.feedback_diagnostics),
        )
        metadata.setdefault(
            "timer_readings", [dict(time=t, value=v, score=s) for t, v, _, s in self.readings]
        )
        metadata["screenshots_available"] = bool(frames)
        counts = Counter(event["result"] for event in self.game_feedback)
        attempts = [item for item in self.attempt_outcomes if item.get("attempt") is not None]
        unknown = sum(item["result"] == "unknown" for item in attempts)
        labels = {
            "caught": "确认捕获",
            "suspected_escape": "疑似超时逃脱",
            "unknown": "结算未确认",
            "interrupted": "已中断",
        }
        self.log.info(
            "本轮结果：%s；游戏反馈：暴击=%d 普通命中=%d 未命中=%d；按键尝试=%d，其中归属未确认=%d；原因=%s",
            labels[self.result.status],
            counts["critical"],
            counts["hit"],
            counts["miss"],
            len(attempts),
            unknown,
            self.result.reason,
        )
        if self.result.status == "caught":
            self.log.info(
                "鱼获：%s，尺寸=%scm（名称为 OCR 读数）", self.result.reward, self.result.size_cm
            )
        if not bundle_writer.submit(
            Path(paths.get_diagnostics_path())
            / "catch_result"
            / ("success" if self.result.status == "caught" else "failures"),
            max(1, self.config.getint("diagnostics", "max_events", fallback=10))
            if self.result.status == "caught"
            else max(1, self.config.getint("diagnostics", "failure_max_events", fallback=100)),
            metadata,
            frames,
            self.save_done,
        ):
            self.log.warning("结算证据队列已满；本轮仅保留结果日志")

    def wait_for_evidence(self):
        if not self.save_done.wait(timeout=1):
            self.log.warning("结算证据仍在后台保存；此时关闭整个程序可能丢失本轮诊断")

    def mark_interrupted(self):
        if self.result.status == "unknown":
            self.result = CatchResult("interrupted", "任务停止，未完成本轮结算观察")
        self.log.debug("结算观察停止: 状态=%s 原因=%s", self.result.status, self.result.reason)


def run_observed_qte(strategy, capture):
    """覆盖正常、超时、异常和停止路径；最终按键归因完成后再保存整轮证据。"""
    reason = "returned"
    try:
        return strategy.play_qte(capture)
    except QTEControlTimeout:
        reason = "control_timeout"
        raise
    except run_control.RunStopped:
        reason = "interrupted"
        raise
    except BaseException as exc:
        reason = f"exception:{type(exc).__name__}"
        raise
    finally:
        strategy._stop_feedback()
        observer = getattr(strategy, "catch_observer", None)
        if observer is not None:
            try:
                observer.finalize(reason)
                observer.wait_for_evidence()
            except Exception:
                log.exception("整条鱼记录收尾失败；保留原流程的停止或异常信号")
