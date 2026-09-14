"""嵌入式图鉴：同一鱼卡只浏览或选目标，列表详情就地展开。"""

import tkinter as tk
from tkinter import ttk

from bd2_fishing.app.fishing_collection import CONDITIONS
from bd2_fishing.ui.collection_widgets import FishPhotos, ViewButtons, clear_children, show_facts
from bd2_fishing.ui.fish_tile import FishTile
from bd2_fishing.ui.scrolling import ScrollablePage


class CataloguePage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=22)
        self.app = app
        self.service = app.services.fish_catalogue_service()
        self.photos = FishPhotos(self.service, self)
        self.view, self.selected, self.picking = "grid", None, False
        self.draft = {}
        self.pick_origin = "catalogue"
        self._resize_id = None
        self._columns = 0
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
        self.source_button = ttk.Button(self, text="资料说明", command=self.about)
        self.source_button.pack(anchor="w", pady=(8, 0))
        self.render()

    def open(self):
        self.app.show_page("catalogue")

    def close(self):
        self.picking = False
        self.draft.clear()

    def resize_cards(self, event):
        columns = (
            max(2, min(5, max(280, event.width - 8) // round(155 * self.photos.scale)))
            if self.view == "grid"
            else 1
        )
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
        self.render()

    def choose(self, identity):
        if self.picking:
            if identity in self.draft:
                del self.draft[identity]
            else:
                self.draft[identity] = next(
                    k for k, v in CONDITIONS.items() if v == self.default_condition.get()
                )
        else:
            self.selected = None if self.selected == identity and self.view == "list" else identity
        self.render()

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
        focus_identity = getattr(self.focus_get(), "fish_identity", None)
        self.tiles = {}
        position = self.browser.canvas.yview()[0]
        self.title.configure(text="选择目标鱼" if self.picking else "鱼种图鉴")
        self.pick_button.configure(
            text="取消选择" if self.picking else "选择目标",
            command=self.cancel if self.picking else self.begin_pick,
        )
        self.views.select(self.view)
        if self.picking:
            self.condition_bar.pack(before=self.count, fill="x", pady=(0, 8))
        else:
            self.condition_bar.pack_forget()
        fish = self.service.search(
            self.query.get(),
            island=self.island.get(),
            time=self.time.get(),
            rarity=self.rarity.get(),
        )
        self.count.configure(text=f"{len(fish)} / {len(self.service.fish)} 种鱼")
        clear_children(self.browser.body)
        clear_children(self.side.body)
        side = self.picking or (self.view == "grid" and self.selected is not None)
        if side:
            self.side.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        else:
            self.side.grid_remove()
        width = max(280, self.browser.canvas.winfo_width() - 8)
        columns = (
            max(2, min(5, width // round(155 * self.photos.scale))) if self.view == "grid" else 1
        )
        self._columns = columns
        for column in range(5):
            self.browser.body.columnconfigure(column, weight=1 if column < columns else 0)
        for index, item in enumerate(fish):
            self._render_card(item, index, columns, width)
        if not fish:
            ttk.Label(self.browser.body, text="没有符合条件的鱼").pack(pady=25)
        self._render_side()
        self.browser.update_idletasks()
        self.browser.canvas.yview_moveto(0 if reset else position)
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
            view=self.view,
            selected=item.id in self.draft if self.picking else self.selected == item.id,
            badge="已选" if self.picking and item.id in self.draft else "",
            colorful=item.rarity == "legendary",
        )
        tile.fish_identity = item.id
        self.tiles[item.id] = tile
        tile.pack(fill="x")
        if self.view == "list" and self.selected == item.id and not self.picking:
            show_facts(
                frame,
                self.service,
                item.id,
                width=max(200, width - round(240 * self.photos.scale)),
                inset=round(108 * self.photos.scale),
            )
            ttk.Button(
                frame,
                text="设为目标",
                command=lambda identity=item.id: self.begin_pick(identity),
            ).pack(anchor="e")

    def _render_side(self):
        if self.picking:
            ttk.Label(
                self.side.body, text=f"已选 {len(self.draft)} 种鱼", style="Section.TLabel"
            ).pack(anchor="w")
            for identity, condition in self.draft.items():
                ttk.Label(self.side.body, text=self.service.by_id[identity].name).pack(
                    anchor="w", pady=(12, 4)
                )
                variable = tk.StringVar(value=CONDITIONS[condition])
                box = ttk.Combobox(
                    self.side.body,
                    values=list(CONDITIONS.values()),
                    textvariable=variable,
                    state="readonly",
                    width=16,
                )
                box.pack(fill="x")
                box.bind(
                    "<<ComboboxSelected>>",
                    lambda _, i=identity, v=variable: self.draft.update(
                        {i: next(k for k, label in CONDITIONS.items() if label == v.get())}
                    ),
                )
            ttk.Button(
                self.side.body,
                text="保存并使用",
                command=self.save,
                state="normal" if self.draft else "disabled",
                style="Start.TButton",
            ).pack(fill="x", pady=16)
        elif self.selected:
            fish = self.service.by_id[self.selected]
            ttk.Label(self.side.body, text=fish.name, style="Section.TLabel").pack(anchor="w")
            ttk.Label(self.side.body, image=self.photos.get(fish.id, (185, 120)) or "").pack(pady=8)
            show_facts(self.side.body, self.service, fish.id, width=180)
            ttk.Button(
                self.side.body, text="设为目标", command=lambda: self.begin_pick(self.selected)
            ).pack(fill="x", pady=8)
            ttk.Button(self.side.body, text="关闭详情", command=self.hide_detail).pack(fill="x")

    def hide_detail(self):
        self.selected = None
        self.render()

    def about(self):
        from tkinter import messagebox

        messagebox.showinfo(
            "资料说明",
            "鱼图来自巴哈姆特，机制参考巴哈姆特和 GameKee。\n名称采用简体参考译名；资料冲突时保留两份记载。\n图鉴机制不代表助手已能自动解除全部机制。",
            parent=self,
        )
