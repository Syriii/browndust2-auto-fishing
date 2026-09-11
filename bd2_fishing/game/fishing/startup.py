"""从已确认的钓鱼页面开始；不把未知画面当作尚未抛竿。"""

import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from bd2_fishing.game.fishing.hook import BITE_TIMEOUT_SECONDS, HookReader
from bd2_fishing.game.fishing.recovery import RoundObservationError, close_confirmed_panel
from bd2_fishing.game.fishing.settlement import CatchObserver
from bd2_fishing.infrastructure import paths
from bd2_fishing.infrastructure.diagnostics import bundle_writer
from bd2_fishing.infrastructure.settings import bounded_float
from bd2_fishing.infrastructure.windows import input as game_input
from bd2_fishing.runtime import control
from bd2_fishing.runtime.context import get_logger

log = get_logger(__name__)


def prepare_start(config, region):
    """返回 idle、waiting 或 qte，启动证据不计为一次鱼获。"""
    return _run_entry_check(config, region, _wait_for_start)


def resume_waiting_for_bite(config, region):
    """接续已抛竿的等待，不执行移动或重抛；返回 hooked、qte 或 idle。"""
    return _run_entry_check(config, region, _wait_for_bite)


def _run_entry_check(config, region, inspect_until_ready):
    observer = CatchObserver(None, config, region)
    details = dict(status="checking", phase=inspect_until_ready.__name__, samples=[])
    observer.evidence_metadata["startup"] = details
    reason = "startup_prepared"
    control.set_status("识别当前游戏页面")
    try:
        state = inspect_until_ready(observer, details)
        details.update(status="ready", next_state=state)
        log.info(
            "%s",
            {
                "idle": "已确认钓鱼待机，准备抛竿。",
                "waiting": "已识别等待咬钩，继续观察，不重复抛竿。",
                "qte": "发现正在进行的 QTE，接续当前鱼，不重复抛竿。",
                "hooked": "检测到咬钩提示，已发送一次拉竿按键。",
            }[state],
        )
        return state
    except BaseException as exc:
        reason = (
            "startup_interrupted" if isinstance(exc, control.RunStopped) else "startup_unconfirmed"
        )
        details.update(
            status="interrupted" if isinstance(exc, control.RunStopped) else "failed",
            error=str(exc),
        )
        raise
    finally:
        if reason != "startup_prepared" or observer.evidence_metadata.get("panel_close_history"):
            try:
                _save_startup(observer, reason)
                observer.wait_for_evidence()
            except Exception:
                log.exception("启动检查证据保存失败，保留原启动结果")


def _save_startup(observer, reason):
    metadata = dict(
        observer.evidence_metadata,
        event=reason,
        evidence_id=uuid.uuid4().hex,
        saved_at_unix=time.time(),
        window_region=observer.window.as_tuple(),
        screenshots_available=bool(observer.evidence_frames),
    )
    observer.save_done.clear()
    if not bundle_writer.submit(
        Path(paths.get_diagnostics_path()) / "startup",
        max(1, observer.config.getint("diagnostics", "failure_max_events", fallback=100)),
        metadata,
        observer.evidence_frames,
        observer.save_done,
    ):
        observer.save_done.set()
        log.warning("启动证据队列已满，请保留诊断日志。")


def _wait_for_start(observer, details):
    budget = bounded_float(observer.config, "recovery", "page_wait_seconds", 10, 0, 60)
    deadline = time.monotonic() + budget
    last_state, since = None, None
    for _ in range(1201):
        control.checkpoint()
        state = observer.inspect_current_page()
        stamp = time.monotonic()
        details["samples"].append(dict(observer.evidence_metadata["resume_check"]))
        if state == "panel":
            log.info("发现可关闭的结算提示，处理后再开始钓鱼。")
            close_confirmed_panel(SimpleNamespace(region=observer.window), observer)
            return "idle"
        if state in {"idle", "waiting", "qte"}:
            if state != last_state:
                since = stamp
            delay = 0.049 if state == "qte" else 0.19
            if since is not None and stamp - since >= delay:
                return state
        else:
            since = None
        last_state = state
        if stamp >= deadline:
            break
        control.sleep(min(0.05, max(0, deadline - stamp)))
    raise RoundObservationError("未确认当前页面，已保存启动现场；请回到钓鱼待机页后开始。")


def _wait_for_bite(observer, details):
    hook = HookReader(observer.config, observer.window)
    deadline = time.monotonic() + BITE_TIMEOUT_SECONDS
    last_state, since = None, None
    control.set_status("接续等待咬钩")
    for _ in range(301):
        control.checkpoint()
        state = observer.inspect_current_page()
        stamp = time.monotonic()
        detected, pixels = (
            hook.inspect(observer.evidence_frames.get("resume_latest.png"))
            if state == "waiting"
            else (False, 0)
        )
        details["samples"].append(
            dict(observer.evidence_metadata["resume_check"], hook_pixels=pixels)
        )
        # 只有本次新帧确认等待页面才使用咬钩信号，未知/QTE/无图都不能触发。
        if state == "waiting" and detected:
            game_input.press("space")
            return "hooked"
        if state in {"idle", "qte"}:
            since = stamp if state != last_state else since
            if since is not None and stamp - since >= (0.049 if state == "qte" else 0.19):
                return state
        else:
            since = None
        last_state = state
        if stamp >= deadline:
            break
        control.sleep(min(0.05, max(0, deadline - stamp)))
    raise RoundObservationError("接续等待咬钩超时，未重抛；已保留页面与咬钩检测依据")
