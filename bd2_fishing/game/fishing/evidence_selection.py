"""轮次摘要保留有诊断意义的画面；QTE 未命中证据由反馈观察器独立保存。"""


def select_round_frames(frames, metadata):
    result = metadata.get("result", {}).get("status")
    resume = metadata.get("resume_check", {}).get("state")
    recovery = metadata.get("round_recovery", {})
    ordinary_return = (
        result in {"unknown", "suspected_escape"}
        and resume in {"idle", "waiting"}
        and metadata.get("page_state") in {"idle", "waiting"}
        and not recovery
        and not metadata.get("stamina_reentry")
    )
    if not ordinary_return:
        return dict(frames)
    # 已正常回到准备页面的空场景无法解释 QTE 未命中；账本和 QTE 原帧仍保留。
    redundant = {"settlement_first.png", "settlement.png", "resume_first.png", "resume_latest.png"}
    return {name: frame for name, frame in frames.items() if name not in redundant}
