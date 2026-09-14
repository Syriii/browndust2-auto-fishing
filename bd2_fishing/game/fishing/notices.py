"""已知游戏提示的动作前核对；仅用于页面恢复，不进入 QTE 实时循环。"""

import re

import cv2


def confirm_exhausted_notice(observer):
    """模板仅筛选外观；完整错误码与提示文字必须同时可读。"""
    frame = observer.evidence_frames.get("resume_latest.png")
    if frame is None or observer.engine is None:
        return False
    normalized = cv2.resize(frame, (945, 532), interpolation=cv2.INTER_AREA)
    texts = observer.engine.detect_and_recognize(normalized[235:274, 380:565])
    observer.evidence_metadata["exhausted_notice_reading"] = [
        dict(text=item.text, score=item.score) for item in texts
    ]
    trusted = [re.sub(r"\s+", "", item.text) for item in texts if item.score >= 0.85]
    return any("已耗尽体力" in text or "已耗盡體力" in text for text in trusted) and any(
        re.search(r"error[:：]150302(?!\d)", text, re.I) for text in trusted
    )
