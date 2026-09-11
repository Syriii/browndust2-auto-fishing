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


def check_unconfirmed_limit(strategy, observer):
    """同一轮只累计一次，避免正常结算失败后进入恢复时重复消耗额度。"""
    if observer.evidence_metadata.get("unconfirmed_counted") is not True:
        strategy._unconfirmed_rounds = (
            0
            if observer.result.status == "caught"
            else getattr(strategy, "_unconfirmed_rounds", 0) + 1
        )
        observer.evidence_metadata["unconfirmed_counted"] = True
    limit = strategy._feedback_config.getint("recovery", "max_unconfirmed_rounds", fallback=2)
    if not 0 <= limit <= 5:
        raise ValueError("未确认续钓上限必须为 0–5")
    if strategy._unconfirmed_rounds > limit:
        raise RuntimeError("连续未确认轮次达到续钓上限，已停止，请检查证据")


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
        check_unconfirmed_limit(strategy, observer)
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
        "继续等待咬钩，不重复抛竿" if details.get("next_state") == "waiting" else "继续下一条鱼",
    )
    return True


def _wait_for_recovery(strategy, observer, details):
    budget = bounded_float(strategy._feedback_config, "recovery", "page_wait_seconds", 10, 0, 60)
    deadline = time.monotonic() + budget
    waiting_since = None
    # 按类型处理新弹窗；同一类型持续出现时只观察，不连续点击。
    for _ in range(301):
        control.checkpoint()
        page = observer.inspect_current_page()
        stamp = time.monotonic()
        details["samples"].append(dict(state=page, captured_at_monotonic=stamp))
        if page == "blocked_dialog" and _panel_kind(observer) == "stamina_error":
            from bd2_fishing.game.navigation.reentry import reenter_after_stamina_error

            reenter_after_stamina_error(observer)
            details["next_state"] = "idle"
            return
        if page == "waiting":
            if waiting_since is not None and stamp - waiting_since >= 0.19:
                details["next_state"] = "waiting"
                return
            waiting_since = stamp if waiting_since is None else waiting_since
        else:
            waiting_since = None
        if page == "panel" and _can_close_panel(observer):
            close_confirmed_panel(strategy, observer)
            return
        if page == "idle":
            observer.wait_until_idle()
            return
        if stamp >= deadline:
            break
        control.sleep(min(0.2, max(0, deadline - stamp)))
    raise RoundObservationError("恢复等待结束，尚未确认结算面板或钓鱼待机控件")
