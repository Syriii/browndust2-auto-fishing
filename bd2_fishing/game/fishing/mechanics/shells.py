"""贝壳实体模板的局部避让；资源在模块载入时读取，逐帧只计算小 ROI。"""

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


def _load_templates():
    root = Path(__file__).resolve().parents[1] / "assets"
    templates = tuple(cv2.imread(str(root / f"shell_body_{i}.png")) for i in range(2))
    if any(template is None for template in templates):
        raise RuntimeError("贝壳识别资源缺失，请检查完整程序包")
    return templates


_TEMPLATES = _load_templates()


@lru_cache(maxsize=8)
def _scaled_templates(height):
    return tuple(
        cv2.resize(t, (round(t.shape[1] * height / t.shape[0]), height)) for t in _TEMPLATES
    )


def read_shell_spans(hsv):
    """返回所有匹配贝壳的横向范围，不赋予消除按键或猜测遮挡光标。"""
    height, width = hsv.shape[:2]
    if height < 8:
        return ()
    # 已有贝壳样本含紫色轮廓；普通蓝黄条无需执行模板匹配。
    purple = cv2.inRange(hsv, (120, 60, 80), (169, 255, 255))
    if cv2.countNonZero(purple) < max(8, height // 2):
        return ()
    frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    candidates = []
    for template in _scaled_templates(height):
        tw = template.shape[1]
        if tw > width:
            continue
        scores = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)[0]
        for x in np.flatnonzero(scores >= 0.90):
            candidates.append((float(scores[x]), int(x), int(x + tw)))
    selected = []
    for _, left, right in sorted(candidates, reverse=True):
        if not any(left < b and right > a for a, b in selected):
            selected.append((left, right))
    return tuple(sorted(selected))
