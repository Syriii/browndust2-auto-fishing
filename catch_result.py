"""整条鱼的结算观察。奖励为确认捕获；超时证据只报告疑似逃脱。"""
from collections import deque
from dataclasses import asdict, dataclass
import itertools
import json
import logging
from pathlib import Path
import queue
import re
import threading
import time
import uuid
from collections import Counter
from zipfile import ZipFile, ZIP_STORED

import cv2
import numpy as np
import run_control
import utils
from feedback_capture import FeedbackCapture
from qte_feedback import white_text
from ocr.ocr_engine import OCRText

from logging_context import get_logger, current_round_id
log = get_logger(__name__)
_jobs = queue.Queue(maxsize=2)
_writer = None
_writer_lock = threading.Lock()
_slots = itertools.count()


@dataclass
class CatchResult:
    status: str = "unknown"
    reason: str = "尚未观察到结算"
    reward: str = ""
    size_cm: float | None = None
    remaining_cm: float | None = None


def distance_value(text):
    normalized = re.sub(r"\s+", "", text).upper().replace("O", "0")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)CM", normalized)
    return float(match.group(1)) if match else None


def _evidence_token(text):
    quantity = re.search(r"[×xX*]\s*([1-9]\d*)", text)
    if quantity:
        return "quantity", int(quantity.group(1))
    distance = distance_value(text)
    return ("distance", distance) if distance is not None else None


def read_settlement_texts(engine, image):
    """对小字的低置信度数量/尺寸放大复核；只接受两次读数一致的关键值。"""
    results = engine.detect_and_recognize(image)
    checked = []
    for item in results:
        token = _evidence_token(item.text)
        if item.score < .85 and item.box is not None and token is not None:
            left, top, right, bottom = item.box.bounds
            crop = image[max(0,top-1):min(image.shape[0],bottom+2),
                         max(0,left-1):min(image.shape[1],right+2)]
            if crop.size:
                refined = engine.recognize(cv2.resize(crop,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC))
                if refined is not None and refined.score >= .85 and _evidence_token(refined.text) == token:
                    item = OCRText(refined.text, refined.score, item.box)
            if item.score < .75 and token[0] == "quantity":
                # 生僻鱼名会拉低整行均分；单独读行尾“×数量”，不伪造未读准的鱼名。
                tail_left = max(left, right-round((bottom-top)*(1+len(str(token[1]))*.5)))
                tail = image[max(0,top-1):min(image.shape[0],bottom+2),
                             max(0,tail_left):min(image.shape[1],right+2)]
                if tail.size:
                    refined = engine.recognize(cv2.resize(tail,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC))
                    if (refined is not None and refined.score >= .80 and
                        re.fullmatch(r"[×xX*]\s*[1-9]\d*", refined.text.strip()) and
                        _evidence_token(refined.text) == token):
                        item = OCRText("×"+str(token[1]), refined.score, item.box)
        checked.append(item)
    return checked


def classify_settlement(panel_open, reward_texts, timer_values, distance_texts):
    """仅使用本轮的明确奖励或超时证据，空画面不表示失败。"""
    reliable = [t.text for t in reward_texts if t.score >= .75]
    rewards = [t for t in reliable if re.search(r"[×xX*]\s*[1-9]\d*", t)]
    sizes = [distance_value(t) for t in reliable]
    sizes = [value for value in sizes if value is not None and value > 0]
    if panel_open and rewards and sizes:
        return CatchResult("caught", "结算关闭提示与鱼奖励数量、尺寸同时出现", rewards[0], sizes[0])
    if panel_open:
        return CatchResult("unknown", "结算面板已出现，但奖励文字未完整识别")
    if rewards and sizes:
        return CatchResult("unknown", "看到奖励文字，但关闭提示未确认；不能判为逃脱")
    distances = [distance_value(t.text) for t in distance_texts if t.score >= .80]
    distances = [value for value in distances if value is not None]
    # 录像中计时器从 1 直接消失，未观察到 0；因此不冒充游戏明确宣告逃脱。
    tail = timer_values[-3:]
    exhausted = ((len(timer_values) >= 2 and all(value <= 1 for value in timer_values[-2:])) or
                 (len(tail) == 3 and tail[-1] <= 1 and tail[0] <= 2 and tail[0] >= tail[1] >= tail[2]))
    if exhausted and distances and distances[-1] > 0:
        return CatchResult("suspected_escape", "倒计时接近耗尽、距离仍大于零，QTE 随后退出；未见奖励面板",
                           remaining_cm=distances[-1])
    return CatchResult("unknown", "QTE 已退出，但缺少可确认的整条鱼结算证据")


def _save_worker():
    while True:
        directory, limit, metadata, frames, done = _jobs.get()
        job_log = get_logger(__name__, metadata.get("round_id"))
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"catch_{next(_slots)%limit+1:02d}.zip"
            temporary = path.with_suffix(".tmp")
            with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
                for name, frame in frames.items():
                    ok, data = cv2.imencode(".png", frame)
                    if not ok:
                        raise RuntimeError("结算证据编码失败")
                    archive.writestr(name, data.tobytes())
                archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
            temporary.replace(path)
            job_log.info("本轮诊断已保存: %s；证据ID=%s", path, metadata["evidence_id"])
        except Exception:
            job_log.exception("结算证据保存失败")
        finally:
            done.set()


class CatchObserver:
    def __init__(self, engine, config, window):
        self.round_id = current_round_id() or uuid.uuid4().hex[:12]
        self.log = get_logger(__name__, self.round_id)
        self.engine, self.config, self.window = engine, config, window
        self.lock = threading.Lock()
        self.readings = deque(maxlen=32)
        self.next_timer_at = 0.0
        self.settling = False
        self.result = CatchResult()
        self.game_feedback = []
        self.attempt_outcomes = []
        self.last_frame = None
        self.last_frame_at = None
        self.evidence_frames = {}
        self.evidence_metadata = {}
        self.finalized = False
        self.save_done = threading.Event()
        self.save_done.set()
        self.close_template = cv2.imdecode(np.frombuffer(
            (Path(__file__).with_name("qte_feedback_assets")/"settlement_close.png").read_bytes(), np.uint8), 1)
        self.close_template = cv2.resize(self.close_template,
            (round(self.close_template.shape[1]*window.width/875),
             round(self.close_template.shape[0]*window.height/492)))

    def observe_timer(self, frame, stamp):
        if self.settling or stamp < self.next_timer_at or not self.lock.acquire(blocking=False):
            return
        self.next_timer_at = stamp+.25
        try:
            # 即使倒计时 OCR 失败，也保留本轮最后一张只读截图。
            self.last_frame, self.last_frame_at = frame.copy(), stamp
            # frame 为原反馈 ROI（客户区 x=30%..70%, y=64%..93%）。
            x1, x2 = round(self.window.width*.022), round(self.window.width*.070)
            y1, y2 = round(self.window.height*.183), round(self.window.height*.238)
            timer = frame[y1:y2, x1:x2]
            value = self.engine.recognize(timer)
            if value is not None and value.score >= .90 and re.fullmatch(r"\d{1,2}", value.text.strip()):
                self.readings.append((stamp, int(value.text.strip()), frame.copy(), value.score))
        except Exception:
            self.log.debug("结算计时器观察失败", exc_info=True)
        finally:
            self.lock.release()

    def _panel_open(self, frame):
        roi = frame[round(self.window.height*.88):round(self.window.height*.97),
                    round(self.window.width*.40):round(self.window.width*.60)]
        score = cv2.minMaxLoc(cv2.matchTemplate(white_text(roi), white_text(self.close_template),
                                               cv2.TM_CCOEFF_NORMED))[1]
        return score >= .85

    def finish(self):
        """QTE 确认退出后、关闭面板前执行；耗时从原结算等待时间中扣除。"""
        self.settling = True
        run_control.checkpoint()
        guard = utils.WindowGuard("BrownDust II", self.window, require_foreground=True)
        guard()
        with FeedbackCapture(self.window) as capture:
            frame = capture.grab()
        captured = time.monotonic()
        # OCR 或取消中途退出时，仍可保存已经取得的现场，不能再截图。
        self.evidence_frames["settlement.png"] = frame
        self.evidence_metadata["captured_at_monotonic"] = captured
        with self.lock:
            readings = list(self.readings)
            panel = self._panel_open(frame)
            reward_texts, distance_texts = [], []
            distance_reading = None
            if panel:
                reward = frame[round(self.window.height*.08):round(self.window.height*.21),
                               round(self.window.width*.36):round(self.window.width*.65)]
                reward_texts = read_settlement_texts(self.engine, reward)
            elif readings and captured-readings[-1][0] <= 4:
                # 最后一帧可能被 FAIL/拳头等特效遮住；有限回看，并保留距离所用的同帧图。
                for reading in list(reversed(readings))[:5:2]:
                    if captured-reading[0] > 4:
                        continue
                    distance_reading = reading
                    distance = reading[2][round(self.window.height*.120):round(self.window.height*.170),
                                          round(self.window.width*.078):]
                    distance_texts = read_settlement_texts(self.engine, distance)
                    run_control.checkpoint()
                    if any(t.score >= .80 and distance_value(t.text) is not None for t in distance_texts):
                        break
            run_control.checkpoint()
            recent = [value for stamp, value, _, _ in readings if captured-stamp <= 4]
            if not panel and recent and recent[-1] <= 1 and any(
                    t.score >= .80 and distance_value(t.text) is not None for t in distance_texts):
                # 关闭提示可能被特效/动画漏识别；先排除实际已有鱼奖励的场景。
                reward = frame[round(self.window.height*.08):round(self.window.height*.21),
                               round(self.window.width*.36):round(self.window.width*.65)]
                reward_texts = read_settlement_texts(self.engine, reward)
                run_control.checkpoint()
            self.result = classify_settlement(panel, reward_texts, recent, distance_texts)
        labels = {"caught": "确认捕获", "suspected_escape": "疑似超时逃脱", "unknown": "未确认"}
        self.log.debug("结算观察依据: 结果=%s 原因=%s 奖励=%s 尺寸cm=%s 剩余cm=%s",
                 labels[self.result.status], self.result.reason, self.result.reward,
                 self.result.size_cm, self.result.remaining_cm)
        self.evidence_metadata = dict(captured_at_monotonic=captured,
            window_region=self.window.as_tuple(), panel_open=panel,
            timer_readings=[dict(time=t, value=v, score=s) for t,v,_,s in readings],
            reward_texts=[asdict(t) for t in reward_texts], distance_texts=[asdict(t) for t in distance_texts],
            distance_frame_at=None if distance_reading is None else distance_reading[0],
            note="success: explicit reward; suspected_escape: visual inference, not explicit game failure")
        if readings:
            self.evidence_frames["last_timer_qte.png"] = readings[-1][2]
        if distance_reading is not None:
            self.evidence_frames["distance_qte.png"] = distance_reading[2]

    def finalize(self, reason):
        """观察线程关闭后落盘完整账本；这里只使用缓存，停止后不截图或 OCR。"""
        if self.finalized:
            return
        self.finalized = True
        self.settling = True
        if reason == "interrupted":
            self.mark_interrupted()
        elif self.result.reason == "尚未观察到结算":
            self.result = CatchResult("unknown", "QTE 控制超时，未观察到结算" if reason == "returned"
                                      else f"QTE 异常退出：{reason}")
        frames = dict(self.evidence_frames)
        if self.last_frame is not None:
            frames["last_observed_qte.png"] = self.last_frame
        metadata = dict(self.evidence_metadata,
            round_id=self.round_id, evidence_id=uuid.uuid4().hex,
            result=asdict(self.result), exit_reason=reason,
            finalized_at_monotonic=time.monotonic(), window_region=self.window.as_tuple(),
            last_observed_at_monotonic=self.last_frame_at,
            game_feedback=list(self.game_feedback), attempt_outcomes=list(self.attempt_outcomes))
        metadata.setdefault("timer_readings", [dict(time=t, value=v, score=s) for t,v,_,s in self.readings])
        metadata["screenshots_available"] = bool(frames)
        counts = Counter(event["result"] for event in self.game_feedback)
        attempts = [item for item in self.attempt_outcomes if item.get("attempt") is not None]
        unknown = sum(item["result"] == "unknown" for item in attempts)
        labels = {"caught": "确认捕获", "suspected_escape": "疑似超时逃脱", "unknown": "结算未确认", "interrupted": "已中断"}
        self.log.info("本轮结果：%s；游戏反馈：暴击=%d 普通命中=%d 未命中=%d；按键尝试=%d，其中归属未确认=%d；原因=%s",
                      labels[self.result.status], counts["critical"], counts["hit"], counts["miss"],
                      len(attempts), unknown, self.result.reason)
        if self.result.status == "caught":
            self.log.info("鱼获：%s，尺寸=%scm（名称为 OCR 读数）", self.result.reward, self.result.size_cm)
        global _writer
        with _writer_lock:
            if _writer is None or not _writer.is_alive():
                _writer = threading.Thread(target=_save_worker, name="catch-evidence", daemon=True)
                _writer.start()
        self.save_done.clear()
        try:
            _jobs.put_nowait((Path(utils.get_base_path())/"debug/catch_result",
                max(1, self.config.getint("diagnostics", "max_events", fallback=10)), metadata, frames, self.save_done))
        except queue.Full:
            self.save_done.set()
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
