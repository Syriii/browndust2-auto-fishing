"""钓鱼界面字形模板的加载与匹配，共用于待机和结算弹窗识别。"""

from pathlib import Path

import cv2
import numpy as np


def load_pattern(name):
    raw = cv2.imdecode(
        np.frombuffer((Path(__file__).with_name("assets") / f"{name}.png").read_bytes(), np.uint8),
        cv2.IMREAD_GRAYSCALE,
    )
    if raw is None or raw.std() < 1:
        raise ValueError("钓鱼界面模板无有效图形")
    return raw


def best_score(gray, patterns):
    best = 0.0
    for pattern in patterns:
        if pattern.std() < 1 or any(a < b for a, b in zip(gray.shape, pattern.shape)):
            continue
        match = cv2.matchTemplate(gray, pattern, cv2.TM_CCOEFF_NORMED)
        finite = match[np.isfinite(match)]
        if finite.size:
            best = max(best, float(finite.max()))
    return best
