"""主窗口图鉴、目标与鱼获的 Tk 检查；临时数据，不操作游戏。"""

import argparse
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from bd2_fishing.app.desktop import DesktopServices
from bd2_fishing.ui.window import FishingApp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visible", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        root = tk.Tk()
        if not args.visible:
            root.withdraw()
        service = DesktopServices(config_path=Path(temporary) / "config.ini", read_only=True)
        app = FishingApp(root, lambda *a, **kw: None, preview=True, services=service)
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)

        def pump():
            for _ in range(8):
                root.update()
                time.sleep(0.03)

        try:
            pump()
            loads = []
            original_photo = app.catalogue.photos.get

            def first_page_photo(*photo_args, **kwargs):
                loads.append(photo_args)
                if args.visible:
                    assert app.run_panel.winfo_viewable()
                    widget = root.winfo_containing(
                        app.deck.winfo_rootx() + 30, app.deck.winfo_rooty() + 30
                    )
                    while widget is not None and widget.master is not app.deck:
                        widget = widget.master
                    assert widget is app.run_panel
                return original_photo(*photo_args, **kwargs)

            with patch.object(app.catalogue.photos, "get", side_effect=first_page_photo):
                app.catalogue.open()
            if args.visible:
                assert loads
                assert not app.run_panel.winfo_viewable()
                assert app.catalogue.tiles[app.catalogue.service.fish[0].id].photo is not None
                assert all(
                    tile.photo is not None
                    for tile in app.catalogue.tiles.values()
                    if tile._visible(tile.winfo_height())
                )
                assert app.catalogue._resize_id is None
            pump()
            panel = app.catalogue
            assert len(panel.service.fish) == 84
            assert len(panel.browser.body.winfo_children()) == 84
            assert all(panel.photos.cache.values())
            if args.visible:
                # 首屏只解码可见图片；移到末尾必须补画，返回页面保留控件和滚动位置。
                assert 0 < sum(tile.photo is not None for tile in panel.tiles.values()) < 84
                panel.browser.canvas.yview_moveto(1)
                pump()
                assert panel.tiles[panel.service.fish[-1].id].photo is not None
                previous_tiles = dict(panel.tiles)
                position = panel.browser.canvas.yview()
                app.show_page("targets")
                pump()
                panel.open()
                pump()
                assert panel.tiles == previous_tiles
                assert panel.browser.canvas.yview() == position
                panel.browser.canvas.yview_moveto(0)
                pump()
            geometry = root.winfo_width(), root.winfo_height()
            first = panel.service.fish[0].id
            panel.change_view("list")
            pump()
            if args.visible:
                panel.browser.canvas.yview_moveto(1)
                pump()
                assert panel.browser.canvas.yview()[1] == 1.0
                assert panel.tiles[panel.service.fish[-1].id].photo is not None
                panel.browser.canvas.yview_moveto(0)
            panel.choose(first)
            pump()
            assert panel.selected == first
            card = panel.browser.body.winfo_children()[0]
            assert len(card.winfo_children()) == 1
            facts = list(panel.details.fields)
            assert "稀有度" in facts and "钓场" in facts and "时段" in facts
            assert "别名" not in facts
            if args.visible:
                tile = panel.tiles[first]
                tile.focus_force()
                tile.event_generate("<Return>")
                pump()
                assert panel.selected == first
                assert root.focus_get() is panel.tiles[first]
                # 鼠标按下后移出卡片松开，不应选中。
                tile = panel.tiles[first]
                tile.event_generate("<Button-1>", x=10, y=10)
                tile.event_generate("<ButtonRelease-1>", x=-5, y=-5)
                assert panel.selected == first
            else:
                panel.choose(first)
                assert panel.selected == first
            panel.query.set("布蘭")
            panel.render(reset=True)
            assert len(panel.browser.body.winfo_children()) == 1
            panel.query.set("不存在的鱼")
            panel.render(reset=True)
            assert panel.count.cget("text").startswith("0 /")
            panel.reset()
            panel.default_condition.set("MAX ＋ MIN")
            panel.begin_pick()
            panel.choose(first)
            with (
                patch.object(
                    app.collection.journal, "replace_targets", side_effect=OSError("disk full")
                ),
                patch("bd2_fishing.ui.window.messagebox.showerror") as error,
            ):
                panel.save()
                assert panel.picking and panel.draft[first] == "both"
                assert app.collection.journal.targets() == []
                error.assert_called_once()
            panel.save()
            pump()
            assert app.collection.journal.targets() == [(first, "max"), (first, "min")]
            assert app.current_page == "targets" and app.task_mode.get() == "按目标钓鱼"
            if args.visible:
                assert app.targets_page.scroll.canvas.winfo_viewable()
                assert app.targets_page.scroll.body.winfo_children()[0].winfo_viewable()
            app.targets_page.edit.invoke()
            pump()
            assert app.current_page == "target-picker"
            assert app.nav_buttons["targets"].instate(["pressed"])
            panel.cancel()
            assert app.current_page == "targets"
            assert app.collection.selected()[first] == "both"
            app.targets_page.remove(first)
            assert app.collection.journal.targets() == []
            evidence = (
                Path(__file__).resolve().parents[2]
                / "tests/fixtures/catch_result/names_20260915/blue-dragon.jpg"
            ).read_bytes()
            for index, (identity, name) in enumerate(
                ((None, "蓝龙海神x1"), ("fish_05_03", "蓝龙海神鳃"), (None, "鱼×1"))
            ):
                app.collection.journal.record(
                    dict(
                        run_id="gallery",
                        round_id=str(index),
                        caught_at=f"2026-09-{14 if index == 0 else 15}T02:03:00+00:00",
                        fish_id=identity,
                        name=name,
                        location="亚特兰蒂斯",
                        size_cm=4.0,
                        size_kind="unknown",
                        rarity="common" if identity else "unknown",
                        stars=1,
                    ),
                    evidence,
                )
            history = app.collection.journal.history()
            app.show_page("catches")
            catches = app.catches_page
            catches.change_category("all")
            pump()
            for view in ("grid", "list"):
                catches.change_view(view)
                pump()
                if args.visible:
                    assert catches.side.winfo_viewable()
                    assert catches.side.winfo_x() > catches.scroll.winfo_x()
                    assert (
                        len(
                            {
                                (tile.photo.width(), tile.photo.height())
                                for tile in catches.tiles.values()
                                if tile.photo is not None
                            }
                        )
                        == 1
                    )
                for item in history:
                    catches.toggle(item["id"])
                    pump()
                    facts = list(catches.details.fields)
                    assert {"捕获时间", "尺寸", "等级", "稀有度", "钓场", "时段"} <= set(facts)
                    assert catches.expanded == item["id"]
            dates = app.collection.journal.history_dates()
            assert len(dates) == 2
            for day in dates:
                catches.day.set(day)
                catches.change_day()
                pump()
                expected = {row["id"] for row in app.collection.journal.history(day=day)}
                assert set(catches.tiles) == expected
                selected = catches.expanded
                catches.change_view("grid")
                pump()
                assert set(catches.tiles) == expected and catches.expanded == selected
                if args.visible:
                    expected_width = catches.scroll.canvas.winfo_width() / catches._columns
                    assert all(
                        tile.winfo_width() <= expected_width for tile in catches.tiles.values()
                    )
                for item in app.collection.journal.history(day=day):
                    assert catches.tiles[item["id"]].footnote == catches._caught_at(item).strftime(
                        "%H:%M"
                    )
            catches.day.set("2099-01-01")
            catches.change_day()
            pump()
            assert not catches.tiles and catches.expanded is None
            catches.day.set("全部日期")
            catches.change_day()
            pump()
            assert len(catches.tiles) == len(history)
            assert app.collection.journal.history() == history
            assert app.collection.journal.targets() == []
            for page in ("run", "catalogue", "catches", "settings", "targets"):
                app.show_page(page)
                pump()
                if args.visible:
                    assert (root.winfo_width(), root.winfo_height()) == geometry
            if args.visible:
                app.show_page("catalogue")
                pump()
                card_button = panel.browser.body.winfo_children()[0].winfo_children()[0]
                before = panel.browser.canvas.yview()[0]
                card_button.event_generate("<MouseWheel>", delta=-120)
                pump()
                assert panel.browser.canvas.yview()[0] > before
            assert not errors, errors
            print(
                "PASS: 84 offline fish, dense grid and fixed facts, list view, filters and traditional search, independent MAX/MIN targets, page geometry and clean close; no game access"
            )
        finally:
            app.close()
            pump()


if __name__ == "__main__":
    main()
