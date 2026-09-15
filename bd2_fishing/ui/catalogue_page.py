"""嵌入式图鉴：左侧密集鱼图或列表，右侧固定详情与目标草稿。"""

import tkinter as tk
from tkinter import ttk

from bd2_fishing.app.fishing_collection import CONDITIONS
from bd2_fishing.ui.collection_widgets import (
    FishDetails,
    FishPhotos,
    ViewButtons,
    clear_children,
    gallery_columns,
)
from bd2_fishing.ui.fish_tile import FishTile
from bd2_fishing.ui.scrolling import ScrollablePage
from bd2_fishing.ui.target_draft import TargetDraft


class CataloguePage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=22)
        self.app = app
        self.service = app.services.fish_catalogue_service()
        self.photos = FishPhotos(self.service, self, crop=False)
        self.view, self.selected, self.picking = "grid", None, False
        self.draft = {}
        self.pick_origin = "catalogue"
        self._resize_id = None
        self._columns = 0
        self._render_key = None
        self._side_key = None
        self._mode_key = None
        self.tiles = {}
        self.query = tk.StringVar()
        self.island = tk.StringVar(value="全部钓场")
        self.time = tk.StringVar(value="全部时段")
        self.rarity = tk.StringVar(value="全部稀有度")
        self.default_condition = tk.StringVar(value=CONDITIONS["any"])
        self.heading = ttk.Frame(self)
        self.heading.pack(fill="x", pady=(0, 12))
        self.title = ttk.Label(self.heading, text="鱼种图鉴", style="Heading.TLabel")
        self.title.pack(side="left")
        self.pick_button = ttk.Button(
            self.heading, text="选择目标", style="Start.TButton", command=self.begin_pick
        )
        self.pick_button.pack(side="right")
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="鱼名", style="Page.TLabel").pack(side="left")
        entry = ttk.Entry(toolbar, textvariable=self.query, width=24)
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda _: self.render(reset=True))
        ttk.Button(toolbar, text="搜索", command=lambda: self.render(reset=True)).pack(side="left")
        self.views = ViewButtons(toolbar, self.change_view)
        self.views.pack(side="right")
        filters = ttk.Frame(self)
        filters.pack(fill="x", pady=(0, 10))
        choices = (
            (
                self.island,
                ["全部钓场", *dict.fromkeys(f.location.value for f in self.service.fish)],
            ),
            (self.time, ["全部时段", "白天", "夜晚"]),
            (self.rarity, ["全部稀有度", "普通", "稀有", "传说"]),
        )
        for label, (variable, values) in zip(("钓场", "时段", "稀有度"), choices):
            group = ttk.Frame(filters)
            group.pack(side="left", fill="x", expand=True, padx=(0, 10))
            ttk.Label(group, text=label, style="PageHint.TLabel").pack(anchor="w", pady=(0, 4))
            box = ttk.Combobox(
                group, textvariable=variable, values=values, state="readonly", width=13
            )
            box.pack(fill="x")
            box.bind("<<ComboboxSelected>>", lambda _: self.render(reset=True))
        ttk.Button(filters, text="重置", command=self.reset).pack(side="left", anchor="s")
        self.condition_bar = ttk.Frame(self, style="Card.TFrame")
        ttk.Label(self.condition_bar, text="新选鱼要求").pack(side="left")
        ttk.Combobox(
            self.condition_bar,
            textvariable=self.default_condition,
            values=list(CONDITIONS.values()),
            state="readonly",
            width=16,
        ).pack(side="left", padx=8)
        ttk.Label(self.condition_bar, text="点击鱼卡选择，再点取消", style="Hint.TLabel").pack(
            side="left"
        )
        self.count = ttk.Label(self, style="PageHint.TLabel")
        self.count.pack(anchor="w", pady=(0, 6))
        self.content = ttk.Frame(self)
        self.content.pack(fill="both", expand=True)
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)
        self.browser = ScrollablePage(self.content, padding=0)
        self.browser.grid(row=0, column=0, sticky="nsew")
        self.browser.canvas.bind("<Configure>", self.resize_cards, add="+")
        self.side = ScrollablePage(self.content, padding=16, surface=True)
        self.side.configure(width=round(240 * self.photos.scale))
        self.side.grid_propagate(False)
        self.side.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.detail_frame = ttk.Frame(self.side.body, style="Card.TFrame")
        self.details = FishDetails(self.detail_frame)
        self.details.pack(fill="x")
        self.choose_target = ttk.Button(
            self.detail_frame, text="设为目标", command=lambda: self.begin_pick(self.selected)
        )
        self.choose_target.pack(fill="x", pady=8)
        self.pick_details = ttk.Frame(self.side.body, style="Card.TFrame")
        self.pick_count = ttk.Label(self.pick_details, style="Section.TLabel")
        self.pick_count.pack(anchor="w")
        self.pick_rows = TargetDraft(self.pick_details, self.service, self._update_draft)
        self.pick_rows.pack(fill="x", pady=(12, 0))
        self.pick_save = ttk.Button(
            self.pick_details, text="保存并使用", command=self.save, style="Start.TButton"
        )
        self.pick_save.pack(fill="x", pady=16)

    def open(self):
        self.app.show_page("catalogue")

    def prepare(self):
        """在旧页面下面完成首屏绘制，列数调整也在显示前收敛。"""
        if (
            self._render_key is not None
            and self._mode_key == self.picking
            and self._resize_id is None
            and (self.winfo_width(), self.winfo_height())
            == (self.master.winfo_width(), self.master.winfo_height())
        ):
            previous = self._render_key
            self.render()
            if previous == self._render_key:
                return
        self.update_idletasks()
        self.render()
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
            self._finish_resize()
        # 被旧页遮住时 Tk 不发送 Expose，显式准备可见鱼卡的 Canvas 内容。
        for tile in self.tiles.values():
            tile.draw()
        self.update_idletasks()

    def close(self):
        self.picking = False
        self.draft.clear()

    def resize_cards(self, event):
        if not self.winfo_ismapped():
            return
        columns = gallery_columns(event.width - 8, self.photos.scale) if self.view == "grid" else 1
        if columns == self._columns:
            return
        if self._resize_id:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(120, self._finish_resize)

    def _finish_resize(self):
        self._resize_id = None
        if self.winfo_exists():
            self.render()

    def reset(self):
        self.query.set("")
        self.island.set("全部钓场")
        self.time.set("全部时段")
        self.rarity.set("全部稀有度")
        self.render(reset=True)

    def change_view(self, view):
        self.view = view
        self.render()

    def begin_pick(self, identity=None, *, origin="catalogue"):
        if self.app.controller.running:
            return
        self.picking = True
        self.pick_origin = origin
        self.selected = None
        self.draft = self.app.collection.selected()
        if identity:
            self.draft.setdefault(
                identity,
                next(k for k, label in CONDITIONS.items() if label == self.default_condition.get()),
            )
        self.app.show_page("target-picker" if origin == "targets" else "catalogue")

    def choose(self, identity):
        if self.picking:
            if identity in self.draft:
                del self.draft[identity]
            else:
                self.draft[identity] = next(
                    k for k, v in CONDITIONS.items() if v == self.default_condition.get()
                )
        else:
            self.selected = identity
        self.render()

    def _update_draft(self, identity, condition):
        self.draft[identity] = condition

    def _sync_picker(self):
        self.pick_count.configure(text=f"已选 {len(self.draft)} 种鱼")
        self.pick_rows.sync(self.draft)
        self.pick_save.state(["!disabled"] if self.draft else ["disabled"])

    def cancel(self):
        self.close()
        self.render()
        if self.pick_origin == "targets":
            self.app.show_page("targets")

    def save(self):
        if self.app.controller.running:
            return
        if not self.app.save_targets(self.draft):
            return
        self.app.task_mode.set("按目标钓鱼")
        self.close()
        self.render()
        self.app.show_page("targets")

    def render(self, reset=False):
        width = max(280, self.browser.canvas.winfo_width() - 8)
        columns = gallery_columns(width, self.photos.scale) if self.view == "grid" else 1
        key = (
            self.view,
            self.query.get(),
            self.island.get(),
            self.time.get(),
            self.rarity.get(),
            columns,
        )
        if self._mode_key != self.picking:
            self._mode_key = self.picking
            self.title.configure(text="选择目标鱼" if self.picking else "鱼种图鉴")
            self.pick_button.configure(
                text="取消选择" if self.picking else "选择目标",
                command=self.cancel if self.picking else self.begin_pick,
            )
            if self.picking:
                self.condition_bar.pack(before=self.count, fill="x", pady=(0, 8))
            else:
                self.condition_bar.pack_forget()
        if key == self._render_key:
            if not self.picking and self.selected not in self.tiles:
                self.selected = next(iter(self.tiles), None)
            self._sync_selection()
            self._render_side()
            if reset:
                self.browser.canvas.yview_moveto(0)
            return
        self._render_key = key
        focus_identity = getattr(self.focus_get(), "fish_identity", None)
        self.tiles = {}
        position = self.browser.canvas.yview()[0]
        self.views.select(self.view)
        fish = self.service.search(
            self.query.get(),
            island=self.island.get(),
            time=self.time.get(),
            rarity=self.rarity.get(),
        )
        if not self.picking and self.selected not in {item.id for item in fish}:
            self.selected = fish[0].id if fish else None
            self._render_key = None
        self.count.configure(text=f"{len(fish)} / {len(self.service.fish)} 种鱼")
        clear_children(self.browser.body)
        width = max(280, self.browser.canvas.winfo_width() - 8)
        columns = gallery_columns(width, self.photos.scale) if self.view == "grid" else 1
        self._columns = columns
        for column in range(12):
            self.browser.body.columnconfigure(
                column,
                weight=1 if column < columns else 0,
                uniform="fish" if column < columns else "",
            )
        for index, item in enumerate(fish):
            self._render_card(item, index, columns, width)
        if not fish:
            ttk.Label(self.browser.body, text="没有符合条件的鱼").pack(pady=25)
        self._render_side()
        self.browser.refresh()
        self.browser.canvas.yview_moveto(0 if reset else position)
        self._render_key = (*key[:-1], columns)
        if focus_identity in self.tiles:
            self.tiles[focus_identity].focus_set()

    def _caption(self, item):
        caption = f"{item.name}\n{'全天' if item.availability == 'both' else '白天' if item.availability == 'day' else '夜晚'}"
        if item.rarity == "legendary":
            caption += " · 彩色"
        if self.picking and item.id in self.draft:
            caption += " · 已选"
        elif self.view == "list":
            caption += "    ▴" if self.selected == item.id else "    ▾"
        return caption

    def _render_card(self, item, index, columns, width):
        frame = ttk.Frame(self.browser.body, style="Card.TFrame", padding=0)
        frame.grid(
            row=index // columns, column=index % columns, sticky="nsew", padx=(0, 8), pady=(0, 9)
        )
        tile = FishTile(
            frame,
            photo=lambda size: self.photos.get(item.id, size),
            name=item.name,
            subtitle=self._caption(item).split("\n", 1)[1].split(" · 已选")[0].split("    ")[0],
            command=lambda identity=item.id: self.choose(identity),
            view="icons" if self.view == "grid" else "list",
            selected=item.id in self.draft if self.picking else self.selected == item.id,
            badge="已选" if self.picking and item.id in self.draft else "",
            colorful=item.rarity == "legendary",
            rank=item.rarity_rank,
        )
        tile.fish_identity = item.id
        self.tiles[item.id] = tile
        tile.pack(fill="x")

    def _sync_selection(self):
        for identity, tile in self.tiles.items():
            selected = identity in self.draft if self.picking else identity == self.selected
            tile.set_selection(selected, "已选" if self.picking and selected else "")

    def _render_side(self):
        key = self.picking, self.selected, tuple(self.draft.items())
        if key == self._side_key:
            return
        self._side_key = key
        if self.picking:
            self.detail_frame.pack_forget()
            if not self.pick_details.winfo_manager():
                self.pick_details.pack(fill="x")
            self._sync_picker()
        else:
            self.pick_details.pack_forget()
            if not self.detail_frame.winfo_manager():
                self.detail_frame.pack(fill="x")
            if self.selected:
                fish = self.service.by_id[self.selected]
                self.details.show(
                    fish.name, self.photos.get(fish.id, (185, 120)), self.service.details(fish.id)
                )
                self.choose_target.state(["!disabled"])
            else:
                self.details.show("没有符合筛选条件的鱼", None, {"facts": (), "mechanisms": ()})
                self.choose_target.state(["disabled"])
        self.side.refresh()
        if not self.picking:
            self.side.canvas.yview_moveto(0)
