"""与具体 OCR 引擎无关的文字及边框值。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OCRBox:
    """OCR 文本框的多边形顶点和检测置信度。"""

    points: tuple[tuple[int, int], ...]
    score: float

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """返回包住所有顶点的轴对齐矩形。"""
        xs = [point[0] for point in self.points]
        ys = [point[1] for point in self.points]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True)
class OCRText:
    """识别文本、置信度及可选的来源文本框。"""

    text: str
    score: float
    box: OCRBox | None = None
