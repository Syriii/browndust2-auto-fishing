"""离线读取已保存原图，输出机制定位和局部耗时；不导入相机、窗口或输入模块。"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np

from bd2_fishing.game.fishing.mechanics.regions import read_mechanism_regions
from bd2_fishing.game.fishing.pointer import read_pointer

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/qte_control"
GREEN = {"green_mixed_000.png", "green_mixed_001.png", "green_only_058.png"}


def replay(directory, *, crop=None, repeats=20):
    records, durations, errors = [], [], []
    files = sorted(directory.glob("*.png"))
    if not files:
        raise ValueError(f"没有 PNG 原图：{directory}")
    for path in files:
        raw = path.read_bytes()
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"无法解码：{path}")
        # 内置夹具包含两种原始 ROI；外部证据必须由使用者明确给出裁剪坐标。
        top, bottom, left, right = crop or (
            (117, 136, 86, 330) if path.name in GREEN else (21, 40, 68, 312)
        )
        if not (0 <= top < bottom <= frame.shape[0] and 0 <= left < right <= frame.shape[1]):
            raise ValueError(f"裁剪超出原图：{path}")
        hsv = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2HSV)
        read_mechanism_regions(hsv)  # 预热不计入局部耗时。
        for _ in range(repeats):
            start = time.perf_counter()
            regions = read_mechanism_regions(hsv)
            durations.append((time.perf_counter() - start) * 1000)
        pointer = read_pointer(hsv)
        record = dict(
            file=path.name,
            sha256=hashlib.sha256(raw).hexdigest(),
            crop=[top, bottom, left, right],
            green_present=bool(regions.green_present),
            green_entry=regions.green.entry if regions.green is not None else None,
            purple_spans=regions.purple_spans,
            red_spans=regions.red_spans,
            blocked_columns=int(np.count_nonzero(regions.blocked)),
            total_columns=hsv.shape[1],
            cursor=pointer.x,
            pointer_reason=pointer.reason,
        )
        records.append(record)
        if directory.resolve() == FIXTURES.resolve() and crop is None:
            if record["green_present"] != (path.name in GREEN):
                errors.append(f"{path.name}: 绿色模式与已标注夹具不符")
            if path.name in GREEN and record["green_entry"] is not None:
                errors.append(f"{path.name}: 未确认起按端不得猜测")
            for name, field in (
                ("red_teeth_11.png", "red_spans"),
                ("purple_content.png", "purple_spans"),
            ):
                if path.name == name and not record[field]:
                    errors.append(f"{path.name}: 局部障碍漏检")
    return dict(
        scope="offline region extraction; no game input or success-rate validation",
        input_directory=str(directory.resolve()),
        records=records,
        errors=errors,
        benchmark=dict(
            samples=len(durations),
            mean_ms=float(np.mean(durations)),
            p95_ms=float(np.percentile(durations, 95)),
            max_ms=max(durations),
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=FIXTURES)
    parser.add_argument("--crop", type=int, nargs=4, metavar=("TOP", "BOTTOM", "LEFT", "RIGHT"))
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".local/maintenance/mechanism-replay.json"
    )
    args = parser.parse_args()
    if not 1 <= args.repeats <= 1000:
        parser.error("--repeats 必须在 1 到 1000 之间")
    if args.input_dir.resolve() != FIXTURES.resolve() and args.crop is None:
        parser.error("外部原图必须显式指定 --crop TOP BOTTOM LEFT RIGHT")
    report = replay(args.input_dir, crop=args.crop, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            dict(frames=len(report["records"]), errors=report["errors"], **report["benchmark"])
        )
    )
    print(args.output.resolve())
    return bool(report["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
