"""隔离配置下测量真实 Tk 交互；耗时包含绘制，不启动游戏。"""

import argparse
import cProfile
import json
import pstats
import statistics
import tempfile
import time
import tkinter as tk
from pathlib import Path

from bd2_fishing.app.desktop import DesktopServices
from bd2_fishing.ui.window import FishingApp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = {}
    with tempfile.TemporaryDirectory() as temporary:
        root = tk.Tk()
        app = FishingApp(
            root,
            lambda *a, **kw: None,
            preview=True,
            services=DesktopServices(config_path=Path(temporary) / "config.ini", read_only=True),
        )
        errors = []
        root.report_callback_exception = lambda *error: errors.append(str(error))

        def measure(name, commands):
            durations = []
            for command in commands:
                start = time.perf_counter()
                command()
                root.update()
                durations.append((time.perf_counter() - start) * 1000)
            results[name] = {
                "count": len(durations),
                "median_ms": round(statistics.median(durations), 2),
                "max_ms": round(max(durations), 2),
                "p95_ms": round(
                    sorted(durations)[min(len(durations) - 1, int(len(durations) * 0.95))], 2
                ),
            }

        try:
            root.update()
            profiler = cProfile.Profile()
            profiler.enable()
            measure("first_catalogue", [app.catalogue.open])
            panel = app.catalogue
            measure("select_fish", [lambda f=f: panel.choose(f.id) for f in panel.service.fish])
            measure(
                "tabs",
                [
                    lambda p=p: app.show_page(p)
                    for _ in range(4)
                    for p in ("run", "catalogue", "targets", "settings", "catalogue")
                ],
            )
            measure("begin_pick", [panel.begin_pick])
            measure("pick_40", [lambda f=f: panel.choose(f.id) for f in panel.service.fish[:40]])
            measure("unpick_40", [lambda f=f: panel.choose(f.id) for f in panel.service.fish[:40]])
            measure(
                "scroll",
                [
                    lambda n=n: panel.browser.canvas.yview_moveto(n / 10)
                    for n in (*range(11), *range(10, -1, -1))
                ],
            )
            profiler.disable()
            with args.output.with_suffix(".profile.txt").open("w", encoding="utf8") as stream:
                pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(45)
            assert not errors, errors
            args.output.write_text(json.dumps(results, indent=2), encoding="utf8")
            print(json.dumps(results, indent=2))
        finally:
            app.close()
            root.update()


if __name__ == "__main__":
    main()
