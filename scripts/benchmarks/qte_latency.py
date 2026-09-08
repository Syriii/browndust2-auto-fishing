"""测量图像原语和日志提交耗时；不代表截图到游戏响应的端到端时延。"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import tempfile
from pathlib import Path
from time import perf_counter_ns

import cv2
import numpy as np

from bd2_fishing.infrastructure.diagnostics.buffered_logging import BufferedHandler
from bd2_fishing.perception.image import create_color_mask

ROOT = Path(__file__).resolve().parents[2]


def measure(operation, iterations):
    for _ in range(100):
        operation()
    samples = []
    for _ in range(iterations):
        started = perf_counter_ns()
        operation()
        samples.append((perf_counter_ns() - started) / 1_000_000)
    return {f"p{p}_ms": float(np.percentile(samples, p)) for p in (50, 95, 99)} | {
        "max_ms": max(samples),
        "samples": iterations,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/benchmarks/qte-latency.json")
    args = parser.parse_args()
    if not 100 <= args.iterations <= 100_000:
        parser.error("iterations must be between 100 and 100000")
    # 固定种子、两个明确尺寸，测量同样工作量；不把合成图当识别正确性证据。
    rng = np.random.default_rng(42)
    results = {}
    for height, width in ((80, 400), (160, 800)):
        frame = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)

        def image_step():
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            white = create_color_mask((0, 0, 185), (180, 105, 255), hsv, is_dilate=False)
            yellow = create_color_mask((20, 50, 50), (35, 255, 255), hsv)
            return np.argmax(np.sum(white, axis=0)), cv2.countNonZero(yellow)

        results[f"image_{width}x{height}"] = measure(image_step, args.iterations)
    with tempfile.TemporaryDirectory() as directory:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        direct = logging.FileHandler(Path(directory) / "direct.log", encoding="utf-8")
        direct.setFormatter(formatter)
        target = logging.FileHandler(Path(directory) / "buffered.log", encoding="utf-8")
        target.setFormatter(formatter)
        buffered = BufferedHandler(target)
        record = logging.LogRecord(
            "benchmark", logging.DEBUG, __file__, 0, "decision %s", (42,), None
        )
        try:
            results["synchronous_file"] = measure(lambda: direct.handle(record), args.iterations)
            results["buffered_submit"] = measure(lambda: buffered.handle(record), args.iterations)
            buffered.flush()
            results["buffered_dropped_records"] = buffered.dropped_records
        finally:
            buffered.close()
            direct.close()
    report = dict(
        scope="offline synthetic image primitives and logging only; no game, capture, input or waits",
        python=platform.python_version(),
        platform=platform.platform(),
        opencv=cv2.__version__,
        results=results,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
