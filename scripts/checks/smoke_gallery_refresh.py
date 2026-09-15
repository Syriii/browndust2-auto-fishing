"""实际 Tk 连续选鱼、回页和缓存淘汰检查；仅使用临时鱼获，不操作游戏。"""

import gc
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from bd2_fishing.app.desktop import DesktopServices
from bd2_fishing.ui.scrolling import ScrollablePage
from bd2_fishing.ui.window import FishingApp


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = tk.Tk()
        app = FishingApp(
            root,
            lambda *a, **kw: None,
            preview=True,
            services=DesktopServices(config_path=Path(temporary) / "config.ini", read_only=True),
        )
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)

        def pump():
            root.update()
            time.sleep(0.02)
            root.update()
            assert not errors, errors

        def visible_photos(page, scroll):
            for fraction in (0, 0.2, 0.4, 0.6, 0.8, 1):
                scroll.canvas.yview_moveto(fraction)
                pump()
                assert all(
                    tile.photo for tile in page.tiles.values() if tile._visible(tile.winfo_height())
                )
            scroll.canvas.yview_moveto(0)
            pump()

        try:
            pump()
            app.catalogue.open()
            pump()
            panel = app.catalogue
            assert not panel.details.note.winfo_ismapped()
            assert panel.choose_target.winfo_rooty() + panel.choose_target.winfo_height() <= (
                panel.side.canvas.winfo_rooty() + panel.side.canvas.winfo_height()
            )
            for view in ("grid", "list"):
                panel.change_view(view)
                pump()
                visible_photos(panel, panel.browser)
                tiles = dict(panel.tiles)
                fields = dict(panel.details.fields)
                position = panel.browser.canvas.yview()
                for fish in panel.service.fish:
                    panel.choose(fish.id)
                    pump()
                    assert panel.tiles == tiles
                    assert panel.details.fields == fields
                    assert panel.details.photo is not None
                    assert panel.browser.canvas.yview() == position
                photo = panel.details.photo
                panel.photos.cache.clear()
                gc.collect()
                pump()
                assert str(photo) in root.tk.call("image", "names")
                assert str(panel.details.picture.cget("image")[0]) == str(photo)
                # 已显示详情自己持有图片，缓存淘汰不能让 Label 变为空白。
                for page in ("run", "settings", "targets", "catalogue"):
                    app.show_page(page)
                    pump()
                assert panel.tiles == tiles
                assert panel.browser.canvas.yview() == position

            # 目标模式沿用鱼卡；连续多选保留现有草稿条件控件。
            tiles = dict(panel.tiles)
            panel.begin_pick()
            pump()
            assert panel.tiles == tiles
            first = panel.service.fish[0].id
            panel.choose(first)
            pump()
            first_rows = panel.pick_rows
            for fish in panel.service.fish[1:40]:
                panel.choose(fish.id)
                pump()
                assert panel.tiles == tiles
                assert panel.pick_rows is first_rows
                assert panel.pick_rows.exists(first)
            panel.pick_rows.edit(first)
            panel.pick_rows.editor.set("MAX ＋ MIN")
            panel.pick_rows.editor.event_generate("<<ComboboxSelected>>")
            pump()
            assert panel.draft[first] == "both"
            panel.cancel()
            pump()
            assert panel.selected is not None
            tile = next(tile for tile in panel.tiles.values() if tile._visible(tile.winfo_height()))
            elements = tile.find_all()
            with patch.object(tile, "photo_provider", wraps=tile.photo_provider) as photo:
                tile._hover(True)
                tile._hover(False)
                assert tile.find_all() == elements
                photo.assert_not_called()
            # 临时滚动容器销毁后不遗留主窗口的滚轮回调。
            binding = root.bind("<MouseWheel>")
            scroll = ScrollablePage(root)
            scroll.destroy()
            assert root.bind("<MouseWheel>").strip() == binding.strip()

            journal = app.collection.journal
            for index, fish in enumerate(panel.service.fish[:8]):
                journal.record(
                    dict(
                        run_id="refresh",
                        round_id=str(index),
                        caught_at=f"2026-09-{14 if index < 4 else 15}T02:00:00+00:00",
                        fish_id=fish.id,
                        name=fish.name,
                        location=fish.location.value,
                        size_cm=40,
                        size_kind="max" if index == 0 else "unknown",
                        rarity=fish.rarity,
                    ),
                    None,
                )
            previous = journal.history()
            app.show_page("run")
            # winfo_containing 依据屏幕层叠；先抬起测试窗口，避免其他应用遮挡。
            root.lift()
            pump()
            catches = app.catches_page
            original_picture = catches.photos.get

            def covered_picture(*args, **kwargs):
                # 第一张鱼图读完前，内容区仍然显示原来的钓鱼页。
                widget = root.winfo_containing(
                    app.deck.winfo_rootx() + 30, app.deck.winfo_rooty() + 30
                )
                while widget is not None and widget.master is not app.deck:
                    widget = widget.master
                assert widget is app.run_panel
                return original_picture(*args, **kwargs)

            with patch.object(catches.photos, "get", side_effect=covered_picture):
                app.show_page("catches")
            pump()
            for view in ("grid", "list"):
                catches.change_view(view)
                pump()
                tiles = dict(catches.tiles)
                with patch.object(journal, "history", wraps=journal.history) as queries:
                    for item in previous:
                        catches.toggle(item["id"])
                        pump()
                        assert catches.tiles == tiles
                        assert catches.details.photo is not None
                    app.show_page("run")
                    app.show_page("catches")
                    pump()
                    assert catches.tiles == tiles
                    queries.assert_not_called()
                # 从 MAX 切到普通记录，旧成就字段应隐藏，不能残留。
                ordinary = next(row for row in previous if row["size_kind"] != "max")
                catches.toggle(ordinary["id"])
                pump()
                assert not catches.details.fields["尺寸成就"][0].winfo_ismapped()
            assert journal.history() == previous
            print(
                "PASS: 84 photos through grid/list scrolling, selections retain cards and fields, image cache eviction, covered first catch paint, return-page reuse and no history queries on selection"
            )
        finally:
            app.close()
            pump()


if __name__ == "__main__":
    main()
