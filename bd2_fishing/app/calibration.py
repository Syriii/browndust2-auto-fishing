"""本机等待精度校准；不发送按键、不把线程测量当作游戏命中率。"""

import math
import statistics
import threading
import time


def measure_waits(cancel=None, *, clock=time.perf_counter):
    cancel = cancel or threading.Event()
    rows = []
    # 与运行控制相同的可取消 Event.wait；每档 32 次，先丢弃一次预热。
    for requested in (5, 10, 20):
        samples = []
        for index in range(33):
            started = clock()
            if cancel.wait(requested / 1000):
                raise RuntimeError("校准已取消")
            elapsed = (clock() - started) * 1000
            if not math.isfinite(elapsed) or elapsed <= 0:
                raise RuntimeError("等待计时无效，请重新校准")
            if index:
                samples.append(elapsed)
        ordered = sorted(samples)
        p95 = ordered[math.ceil(len(ordered) * 0.95) - 1]
        rows.append(
            dict(
                requested_ms=requested,
                samples_ms=samples,
                median_ms=round(statistics.median(samples), 3),
                p95_ms=round(p95, 3),
                max_ms=round(max(samples), 3),
                stable=p95 <= requested + max(2, requested * 0.25),
            )
        )
    usable = [row["requested_ms"] for row in rows if row["stable"]]
    # 这是明确的基础节流启发式；调度波动过大时不给自动填入值。
    selected = min(usable) if usable else None
    return dict(
        schema_version=1,
        measured_at_unix=time.time(),
        method="threading.Event.wait; 32 samples per interval after warmup",
        waits=rows,
        recommendation={}
        if selected is None
        else {
            "loop_sleep_seconds": str(selected),
            "feedback_poll_seconds": str(max(10, selected)),
        },
        recommendation_unit="milliseconds",
        reason="采用 p95 超时偏差不超过 max(2ms, 请求值的25%) 的最小候选；反馈间隔至少10ms。"
        if usable
        else "各档等待均有较大调度波动，保留当前设置，稍后重新测量。",
        limitation="基础节流建议不包含截图、识别、输入驱动或游戏响应；按住和松开后等待仍需游戏验证。",
    )
