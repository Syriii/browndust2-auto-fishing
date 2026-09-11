"""失败轮次的页面恢复；只在 QTE 输入及观察器清理完成后执行。"""

import time
import traceback

from bd2_fishing.infrastructure.settings import bounded_float
from bd2_fishing.infrastructure.windows import input as game_input
from bd2_fishing.runtime import control
from bd2_fishing.runtime.context import get_logger

log = get_logger(__name__)


class RoundObservationError(TimeoutError):
    """本轮未能确认页面或结果，可在释放输入后重新检查是否具备续钓条件。"""


def record_unconfirmed_round(strategy, observer):
    """只记录未确认次数；能否续钓由当前页面决定，不按鱼获统计中止任务。"""
    if observer.evidence_metadata.get("unconfirmed_counted") is not True:
        strategy._unconfirmed_rounds = (
            0
            if observer.result.status == "caught"
            else getattr(strategy, "_unconfirmed_rounds", 0) + 1
        )
        observer.evidence_metadata["unconfirmed_counted"] = True
    observer.evidence_metadata["consecutive_unconfirmed_rounds"] = strategy._unconfirmed_rounds


def _panel_kind(observer):
    return observer.evidence_metadata.get("resume_check", {}).get("panel_kind", "result")


def _closed_panels(observer):
    metadata = observer.evidence_metadata
    return metadata.get(
        "closed_panel_kinds", ["result"] if metadata.get("panel_close_attempted") is True else []
    )


def _can_close_panel(observer):
    kind = _panel_kind(observer)
    return kind in {"result", "level_up"} and kind not in _closed_panels(observer)


def _close_new_panel(strategy, observer):
    """每种已知结算弹窗只关闭一次；移动后须复核仍是同一种弹窗。"""
    if not _can_close_panel(observer):
        return False
    kind = _panel_kind(observer)
    game_input.moveTo(*strategy.region.center)
    control.sleep(0.2)
    if observer.inspect_current_page() != "panel" or _panel_kind(observer) != kind:
        raise RoundObservationError("关闭前未再次确认面板，未发送点击")
    closed = list(_closed_panels(observer))
    closed.append(kind)
    observer.evidence_metadata["closed_panel_kinds"] = closed
    observer.evidence_metadata["panel_close_attempted"] = True
    attempt = dict(
        kind=kind,
        attempted_at_monotonic=time.monotonic(),
        status="attempting",
        inspection=dict(observer.evidence_metadata.get("resume_check", {})),
    )
    observer.evidence_metadata.setdefault("panel_close_history", []).append(attempt)
    frame = observer.evidence_frames.get("resume_latest.png")
    if frame is not None:
        observer.evidence_frames[f"panel_before_{kind}.png"] = frame
    if kind == "level_up":
        log.info("钓鱼等级提升，正在关闭升级提示并继续。")
    game_input.click()
    attempt["status"] = "sent"
    return True


def close_confirmed_panel(strategy, observer):
    """处理鱼获和后续升级弹窗，最后确认待机；不在 QTE 实时路径运行。"""
    if not _close_new_panel(strategy, observer):
        raise RoundObservationError("当前弹窗已发送关闭点击，等待页面响应，不重复点击")
    observer.wait_until_idle(on_panel=lambda: _close_new_panel(strategy, observer))


def recover_round(strategy, observer, error):
    """保留原故障，仅在重新确认待机后允许下一轮；未知页面不补按。"""
    details = dict(
        status="checking",
        error_type=type(error).__name__,
        error=str(error),
        traceback="".join(traceback.format_exception(error)),
        started_at_monotonic=time.monotonic(),
        samples=[],
    )
    observer.evidence_metadata["round_recovery"] = details
    # 已缓存的故障帧不可被后续恢复检查覆盖。
    for name in ("settlement.png", "resume_latest.png"):
        if name in observer.evidence_frames:
            observer.evidence_frames[f"failure_{name}"] = observer.evidence_frames[name]
    log.warning("本轮出现问题，正在检查能否恢复续钓；异常现场将保留。")
    log.debug("本轮待恢复异常", exc_info=(type(error), error, error.__traceback__))
    control.set_status("本轮异常，等待页面恢复")
    try:
        record_unconfirmed_round(strategy, observer)
        _wait_for_recovery(strategy, observer, details)
    except control.RunStopped:
        details["status"] = "interrupted"
        raise
    except Exception as recovery_error:
        details.update(status="failed", recovery_error=str(recovery_error))
        error.add_note(f"本轮恢复未完成：{type(recovery_error).__name__}: {recovery_error}")
        log.warning("本轮自动恢复未完成：%s；请检查异常截图。", recovery_error)
        return False
    finally:
        details["finished_at_monotonic"] = time.monotonic()
    details["status"] = "resumed"
    log.info(
        "页面已恢复，本轮问题已记录，%s。",
        {"waiting": "继续等待咬钩，不重复抛竿", "qte": "接续当前 QTE"}.get(
            details.get("next_state"), "继续下一条鱼"
        ),
    )
    return True


def _wait_for_recovery(strategy, observer, details):
    budget = max(
        1.0, bounded_float(strategy._feedback_config, "recovery", "page_wait_seconds", 10, 0, 60)
    )
    deadline = time.monotonic() + budget
    ready_since, previous_page = None, None
    # 按类型处理新弹窗；同一类型持续出现时只观察，不连续点击。
    while True:
        control.checkpoint()
        page = observer.inspect_current_page()
        stamp = time.monotonic()
        details["samples"].append(dict(state=page, captured_at_monotonic=stamp))
        # 长期恢复仅保留最近采样；总观察次数单独统计，不无限增加证据体积。
        details["observations"] = details.get("observations", 0) + 1
        del details["samples"][:-300]
        if page == "blocked_dialog" and _panel_kind(observer) == "stamina_error":
            from bd2_fishing.game.navigation.reentry import reenter_after_stamina_error

            reenter_after_stamina_error(observer)
            details["next_state"] = "idle"
            return
        if page in {"waiting", "qte"}:
            ready_since = stamp if page != previous_page else ready_since
            delay = 0.049 if page == "qte" else 0.19
            if ready_since is not None and stamp - ready_since >= delay:
                details["next_state"] = page
                return
        else:
            ready_since = None
        previous_page = page
        try:
            if page == "panel" and _can_close_panel(observer):
                close_confirmed_panel(strategy, observer)
                return
            if page == "idle":
                observer.wait_until_idle()
                return
        except RoundObservationError as exc:
            # 转场或已发送的关闭尚未生效，继续观察；不重复关闭同一弹窗。
            details["last_transition_error"] = str(exc)
        if stamp >= deadline:
            details["pending_windows"] = details.get("pending_windows", 0) + 1
            log.warning("页面暂未恢复，任务仍在等待；识别到可继续的页面后自动接续。")
            control.set_status("等待页面恢复，任务未停止")
            deadline = stamp + max(10.0, budget)
        control.sleep(min(0.2, max(0, deadline - stamp)))
