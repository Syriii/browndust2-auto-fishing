"""真实 Tk 本次鱼获与时段设置检查，使用临时库和模拟启动，不操作游戏。"""

import argparse
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import ImageGrab

from bd2_fishing.app.desktop import DesktopServices
from bd2_fishing.app.fishing_collection import TIME_POLICIES
from bd2_fishing.ui.window import FishingApp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-screenshots", action="store_true")
    args = parser.parse_args()
    evidence = Path(".local/maintenance/compact-catches-20260915")
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        root = tk.Tk()
        app = FishingApp(
            root,
            lambda *a, **k: None,
            preview=True,
            services=DesktopServices(config_path=Path(temp) / "config.ini"),
        )
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)

        def pump():
            root.update()
            time.sleep(0.03)
            root.update()
            assert not errors, errors

        try:
            app.collection.begin()

            def record(index, fish="fish_05_12", run=None, name="丝带x1", raw_path=None):
                event = dict(
                    run_id=run or app.collection.run_id,
                    round_id=str(index),
                    caught_at="2026-09-15T07:00:00+00:00",
                    fish_id=fish,
                    name=name,
                    location="亚特兰蒂斯",
                    size_cm=94,
                    size_kind="max" if index == 1 else "unknown",
                    rarity="rare",
                    stars=2,
                )
                raw = (
                    Path(
                        raw_path or "tests/fixtures/catch_result/ribbon_eel_20260915/catch-233.jpg"
                    ).read_bytes()
                    if fish is None
                    else None
                )
                app.collection.journal.record(event, raw)

            record(0, run="previous")
            record(1)
            record(2, fish=None)
            pump()
            app.session_catches.refresh()
            pump()
            assert len(app.session_catches.tiles) == 2
            retained = dict(app.session_catches.tiles)
            for tile in app.session_catches.tiles.values():
                tile.draw()
                assert tile.photo is not None
            with patch.object(
                app.collection.journal,
                "history",
                side_effect=AssertionError("unchanged panel queried history"),
            ):
                app.session_catches.refresh()
            selected = next(iter(app.session_catches.tiles))
            app.session_catches.tiles[selected].command()
            pump()
            assert app.current_page == "catches"
            assert app.catches_page.category == "all"
            assert app.catches_page.expanded == selected
            app.show_page("run")
            record(
                3,
                fish=None,
                name="神仙鱼x1",
                raw_path="tests/fixtures/catch_result/angelfish_20260915/catch-252.jpg",
            )
            app.session_catches.refresh()
            pump()
            angelfish = next(
                tile for tile in app.session_catches.tiles.values() if tile.name == "神仙鱼"
            )
            angelfish.draw()
            assert angelfish.photo is not None
            assert all(app.session_catches.tiles[key] is tile for key, tile in retained.items())
            for geometry in ("1100x760", "960x640"):
                root.geometry(geometry)
                pump()
                assert app.text.winfo_height() >= 80, app.text.winfo_height()
                assert (
                    app.session_catches.winfo_rootx()
                    >= app.log_panel.winfo_rootx() + app.log_panel.winfo_width()
                )
                assert (
                    app.session_catches.winfo_rootx() + app.session_catches.winfo_width()
                    <= root.winfo_rootx() + root.winfo_width()
                )
                assert app.update_button.winfo_rootx() >= app.text.winfo_rootx()
                root.lift()
                pump()
                if not args.no_screenshots:
                    ImageGrab.grab(
                        (
                            root.winfo_rootx(),
                            root.winfo_rooty(),
                            root.winfo_rootx() + root.winfo_width(),
                            root.winfo_rooty() + root.winfo_height(),
                        )
                    ).save(evidence / f"run-{geometry}.png")
            for index in range(4, 34):
                record(index)
            app.session_catches.refresh()
            assert len(app.session_catches.tiles) == 30
            assert app.session_catches.heading.cget("text") == "本次鱼获 · 33"
            pump()
            for index, tile in enumerate(app.session_catches.tiles.values()):
                assert tile.is_compact
                assert tile.footnote == ""
                assert tile.winfo_reqheight() <= round(60 * tile.scale)
            assert {
                int(tile.grid_info()["column"]) for tile in app.session_catches.tiles.values()
            } == {0, 1, 2, 3}
            app.collection.save_targets({"fish_05_14": "max"})
            app.task_mode.set("按目标钓鱼")
            app.time_policy.set(TIME_POLICIES["continuous"])
            app.controller.start = Mock()
            app.preview = False
            app.start()
            app.controller.start.assert_called_once()
            assert not app.collection.wait_for_time
            assert app.services.load_settings().get("app", "target_time_policy") == "continuous"
            assert not app.session_catches.tiles
            assert app.session_catches.heading.cget("text") == "本次鱼获 · 0"
            assert len(app.collection.journal.history(limit=100)) == 34
            print(
                "PASS: session-only images, unknown-name icon, counts, 30-card bound, unchanged-page reuse, new-start reset, persistent time policy, minimum/default layout; no game input"
            )
        finally:
            app.close()
            for _ in range(5):
                time.sleep(0.06)
                try:
                    root.update()
                except tk.TclError:
                    break
            app.collection.journal.close()


if __name__ == "__main__":
    main()
