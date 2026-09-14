"""目标待办与带图鱼获历史，编辑只发生在待机时。"""

import tkinter as tk
from datetime import datetime
from tkinter import ttk

from bd2_fishing.app.fishing_collection import CONDITIONS
from bd2_fishing.ui.collection_widgets import FishPhotos, ViewButtons, clear_children, show_facts
from bd2_fishing.ui.fish_tile import FishTile
from bd2_fishing.ui.scrolling import ScrollablePage


class TargetsPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=22)
        self.app = app
        self.service = app.services.fish_catalogue_service()
        self.photos = FishPhotos(self.service, self)
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="钓鱼目标", style="Heading.TLabel").pack(side="left")
        self.edit = ttk.Button(
            header,
            text="添加目标",
            style="Start.TButton",
            command=lambda: app.catalogue.begin_pick(origin="targets"),
        )
        self.edit.pack(side="right")
        self.scroll = ScrollablePage(self, padding=0)
        self.scroll.pack(fill="both", expand=True)
        self.summary = ttk.Label(self, style="PageHint.TLabel")
        self.summary.pack(fill="x", pady=10)

    def remove(self, identity):
        if self.app.controller.running:
            return
        selected = self.app.collection.selected()
        selected.pop(identity, None)
        self.app.save_targets(selected)
        self.render()

    def update_condition(self, identity, value):
        if self.app.controller.running:
            return
        selected = self.app.collection.selected()
        selected[identity] = next(k for k, label in CONDITIONS.items() if label == value)
        if not self.app.save_targets(selected):
            self.render()

    def render(self):
        clear_children(self.scroll.body)
        selected = self.app.collection.selected()
        active = self.app.controller.running
        self.edit.configure(state="disabled" if active else "normal")
        for identity, condition in selected.items():
            fish = self.service.by_id[identity]
            row = ttk.Frame(self.scroll.body, padding=16, style="Sheet.TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, image=self.photos.get(identity, (85, 58)) or "").pack(
                side="left", padx=(0, 12)
            )
            text = f"{fish.name}\n{fish.location.value} · {'全天' if fish.availability == 'both' else '白天' if fish.availability == 'day' else '夜晚'}"
            ttk.Label(row, text=text).pack(side="left")
            ttk.Button(
                row,
                text="移除",
                command=lambda i=identity: self.remove(i),
                state="disabled" if active else "normal",
            ).pack(side="right", padx=(10, 0))
            variable = tk.StringVar(value=CONDITIONS[condition])
            box = ttk.Combobox(
                row,
                textvariable=variable,
                values=list(CONDITIONS.values()),
                state="disabled" if active else "readonly",
                width=16,
            )
            box.pack(side="right")
            box.bind(
                "<<ComboboxSelected>>",
                lambda _, i=identity, v=variable: self.update_condition(i, v.get()),
            )
        if not selected:
            ttk.Label(self.scroll.body, text="暂无待完成目标", style="Section.TLabel").pack(
                pady=(35, 12)
            )
            ttk.Label(
                self.scroll.body,
                text="先选任意尺寸、MAX、MIN 或两者，再选鱼图。",
                style="Hint.TLabel",
            ).pack()
        count = len(self.app.collection.journal.targets())
        self.summary.configure(text=f"待完成 {count} 项要求 · 完成后移出待办，鱼获保留在历史中")


class CatchesPage(ttk.Frame):
    CATEGORIES = {"全部": "all", "首次": "first", "彩色": "color", "最大": "max", "最小": "min"}

    def __init__(self, parent, app):
        super().__init__(parent, padding=22)
        self.app = app
        self.service = app.services.fish_catalogue_service()
        self.photos = FishPhotos(self.service, self)
        self.category, self.view, self.expanded = "first", "list", None
        self.limit = 80
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Label(toolbar, text="鱼获记录", style="Heading.TLabel").pack(side="left")
        self.views = ViewButtons(toolbar, self.change_view)
        self.views.pack(side="right")
        tabs = ttk.Frame(self)
        tabs.pack(fill="x", pady=(0, 10))
        self.tabs = {}
        for text, key in self.CATEGORIES.items():
            button = ttk.Button(tabs, text=text, command=lambda k=key: self.change_category(k))
            button.pack(side="left", padx=(0, 8))
            self.tabs[key] = button
        self.scroll = ScrollablePage(self, padding=0)
        self.scroll.pack(fill="both", expand=True)
        self.more = ttk.Button(self, text="加载更早记录", command=self.load_more)
        self.notice = ttk.Label(self, style="PageHint.TLabel")
        self.notice.pack(fill="x", pady=(10, 0))

    def change_category(self, category):
        self.category, self.limit, self.expanded = category, 80, None
        self.render(reset=True)

    def change_view(self, view):
        self.view = view
        self.render()

    def load_more(self):
        self.limit += 80
        self.render()

    def toggle(self, identity):
        self.expanded = None if self.expanded == identity else identity
        self.render()

    def render(self, reset=False):
        position = self.scroll.canvas.yview()[0]
        clear_children(self.scroll.body)
        self.views.select(self.view)
        for key, button in self.tabs.items():
            button.state(["pressed"] if key == self.category else ["!pressed"])
        rows = self.app.collection.journal.history(self.category, limit=self.limit + 1)
        for col in range(3):
            self.scroll.body.columnconfigure(
                col, weight=1 if self.view == "grid" or col == 0 else 0
            )
        columns = 3 if self.view == "grid" else 1
        for index, item in enumerate(rows[: self.limit]):
            self._render_catch(item, index, columns)
        if not rows:
            ttk.Label(self.scroll.body, text="暂无这类鱼获", style="Section.TLabel").grid(pady=35)
        if len(rows) > self.limit:
            self.more.pack(before=self.notice, pady=8)
        else:
            self.more.pack_forget()
        self.notice.configure(text=f"已显示 {min(len(rows), self.limit)} 条")
        self.scroll.refresh()
        self.scroll.canvas.yview_moveto(0 if reset else position)

    @staticmethod
    def _label(item):
        tags = []
        if item["stars"] is not None:
            tags.append(f"{item['stars']} 级")
        if item["size_kind"] in ("max", "min"):
            tags.append(item["size_kind"].upper())
        if item["new_record"]:
            tags.append("新纪录")
        size = f"{item['size_cm']} cm" if item["size_cm"] is not None else "尺寸未确认"
        label = f"{item['name']}\n{size}  {' · '.join(tags)}"
        return label

    def _render_catch(self, item, index, columns):
        card = ttk.Frame(self.scroll.body, padding=0, style="Card.TFrame")
        card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=4, pady=4)

        def picture(size):
            photo = self.photos.get(item["fish_id"], size) if item["fish_id"] else None
            return photo if photo is not None else self.app.collection_photo(item, size)

        FishTile(
            card,
            photo=picture,
            name=item["name"],
            subtitle=self._label(item).split("\n", 1)[1],
            view=self.view,
            command=lambda i=item["id"]: self.toggle(i),
            selected=self.expanded == item["id"],
            colorful=item["rarity"] == "legendary",
        ).pack(fill="x")
        if self.expanded == item["id"]:
            self._show_details(card, item, columns)

    def _show_details(self, card, item, columns):
        try:
            caught_at = (
                datetime.fromisoformat(item["caught_at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            )
        except ValueError:
            caught_at = item["caught_at"]
        ttk.Label(
            card,
            text=f"{item['location']} · {caught_at}",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=8)
        if item["fish_id"]:
            show_facts(card, self.service, item["fish_id"], width=180 if columns == 3 else 480)
