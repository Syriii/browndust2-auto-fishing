"""目标待办与带图鱼获历史，编辑只发生在待机时。"""

import tkinter as tk
from collections import OrderedDict
from datetime import datetime
from tkinter import ttk

from bd2_fishing.app.fishing_collection import CONDITIONS
from bd2_fishing.ui.collection_widgets import (
    FishPhotos,
    ViewButtons,
    clear_children,
    gallery_columns,
    show_details,
)
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
        self.photos = FishPhotos(self.service, self, crop=False)
        self.category, self.view, self.expanded = "first", "grid", None
        self.limit, self._columns = 80, 0
        self._resize_id = None
        self.tiles = {}
        self._references = OrderedDict()
        self.day = tk.StringVar(value="全部日期")
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
        dates = ttk.Frame(self)
        dates.pack(fill="x", pady=(0, 8))
        ttk.Label(dates, text="日期", style="Page.TLabel").pack(side="left")
        self.date_box = ttk.Combobox(dates, textvariable=self.day, state="readonly", width=18)
        self.date_box.pack(side="left", padx=8)
        self.date_box.bind("<<ComboboxSelected>>", lambda _: self.change_day())
        content = ttk.Frame(self)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        self.scroll = ScrollablePage(content, padding=0)
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.canvas.bind("<Configure>", self.resize_cards, add="+")
        self.side = ScrollablePage(content, padding=16, surface=True)
        self.side.configure(width=round(240 * self.photos.scale))
        self.side.grid_propagate(False)
        self.side.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.more = ttk.Button(self, text="加载更早记录", command=self.load_more)
        self.notice = ttk.Label(self, style="PageHint.TLabel")
        self.notice.pack(fill="x", pady=(10, 0))

    def resize_cards(self, event):
        if not self.winfo_ismapped():
            return
        columns = gallery_columns(event.width - 8, self.photos.scale) if self.view == "grid" else 1
        if columns == self._columns:
            return
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(120, self._finish_resize)

    def _finish_resize(self):
        self._resize_id = None
        self.render()

    def change_category(self, category):
        self.category, self.limit, self.expanded = category, 80, None
        self.render(reset=True)

    def change_view(self, view):
        self.view = view
        self.render()

    def change_day(self):
        self.limit, self.expanded = 80, None
        self.render(reset=True)

    def load_more(self):
        self.limit += 80
        self.render()

    def toggle(self, identity):
        self.expanded = identity
        self.render()

    def render(self, reset=False):
        position = self.scroll.canvas.yview()[0]
        clear_children(self.scroll.body)
        clear_children(self.side.body)
        self.tiles = {}
        self.views.select(self.view)
        for key, button in self.tabs.items():
            button.state(["pressed"] if key == self.category else ["!pressed"])
        self.date_box.configure(
            values=[
                "全部日期",
                *(day or "日期未确认" for day in self.app.collection.journal.history_dates()),
            ]
        )
        day = self.day.get()
        rows = self.app.collection.journal.history(
            self.category,
            limit=self.limit + 1,
            day=None if day == "全部日期" else "unknown" if day == "日期未确认" else day,
        )
        visible = rows[: self.limit]
        if self.expanded not in {item["id"] for item in visible}:
            self.expanded = visible[0]["id"] if visible else None
        width = self.scroll.canvas.winfo_width() - 8
        columns = gallery_columns(width, self.photos.scale) if self.view == "grid" else 1
        self._columns = columns
        for col in range(12):
            self.scroll.body.columnconfigure(
                col, weight=1 if col < columns else 0, uniform="fish" if col < columns else ""
            )
        groups = OrderedDict()
        for item in visible:
            caught_at = self._caught_at(item)
            date = caught_at.date().isoformat() if caught_at else "日期未确认"
            groups.setdefault(date, []).append(item)
        row = 0
        for date, items in groups.items():
            caption = f"今天 · {date}" if date == datetime.now().date().isoformat() else date
            ttk.Label(self.scroll.body, text=caption, style="PageHint.TLabel").grid(
                row=row, column=0, columnspan=columns, sticky="w", padx=4, pady=(8, 4)
            )
            for index, item in enumerate(items):
                self._render_catch(item, index, columns, row + 1)
            row += 1 + (len(items) + columns - 1) // columns
        if not rows:
            ttk.Label(self.scroll.body, text="暂无这类鱼获", style="Section.TLabel").grid(pady=35)
            ttk.Label(self.side.body, text="捕获后可在这里查看详情", style="Hint.TLabel").pack(
                pady=16
            )
        if len(rows) > self.limit:
            self.more.pack(before=self.notice, pady=8)
        else:
            self.more.pack_forget()
        self.notice.configure(text=f"已显示 {min(len(rows), self.limit)} 条")
        self.side.refresh()
        self.scroll.refresh()
        self.scroll.canvas.yview_moveto(0 if reset else position)

    @staticmethod
    def _caught_at(item):
        try:
            return datetime.fromisoformat(item["caught_at"]).astimezone()
        except (ValueError, TypeError):
            return None

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
        return f"{size}  {' · '.join(tags)}"

    def _picture(self, item, fish, size):
        return self.photos.get(fish.id, size) if fish else None

    def _reference(self, item):
        key = item["id"], item["fish_id"], item["name"], item["location"]
        if key not in self._references:
            fish = self.service.catch_reference(item)
            source = "confirmed" if item["fish_id"] else "name"
            if fish is None:
                fish = self.service.catch_image_reference(
                    self.app.collection.journal.evidence(item["id"]), item["location"]
                )
                source = "image"
            self._references[key] = fish, source
        self._references.move_to_end(key)
        while len(self._references) > 256:
            self._references.popitem(last=False)
        return self._references[key]

    def _render_catch(self, item, index, columns, row_offset=0):
        card = ttk.Frame(self.scroll.body, padding=0, style="Card.TFrame")
        card.grid(
            row=row_offset + index // columns, column=index % columns, sticky="nsew", padx=4, pady=4
        )
        fish, source = self._reference(item)
        name = fish.name if fish else self.service.catch_name(item["name"])
        caught_at = self._caught_at(item)
        time = caught_at.strftime("%H:%M") if caught_at else "时间未确认"
        tile = FishTile(
            card,
            photo=lambda size: self._picture(item, fish, size),
            name=name,
            subtitle=f"{self._label(item)} · {time}",
            view="icons" if self.view == "grid" else "list",
            command=lambda i=item["id"]: self.toggle(i),
            selected=self.expanded == item["id"],
            colorful=item["rarity"] == "legendary",
            rank=item["stars"],
            footnote=time,
            measurement=f"{item['size_cm']:g}cm" if item["size_cm"] is not None else "尺寸未确认",
            marker=item["size_kind"].upper() if item["size_kind"] in ("max", "min") else "",
        )
        self.tiles[item["id"]] = tile
        tile.pack(fill="x")
        if self.expanded == item["id"]:
            self._show_details(item, fish, name, source)

    def _show_details(self, item, fish, name, source):
        panel = self.side.body
        ttk.Label(panel, text=name, style="Section.TLabel").pack(anchor="w")
        photo = self.photos.get(fish.id, (185, 120)) if fish else None
        self.detail_photo = photo
        ttk.Label(panel, image=photo or "", text="" if photo else "待补充图鉴资料").pack(pady=8)
        timestamp = self._caught_at(item)
        caught_at = timestamp.strftime("%Y-%m-%d %H:%M:%S") if timestamp else item["caught_at"]
        details = (
            self.service.details(fish.id)
            if fish
            else {
                "facts": (("稀有度", "未确认"), ("钓场", item["location"]), ("时段", "未确认")),
                "mechanisms": (),
            }
        )
        details["facts"] = (
            *details["facts"],
            ("捕获时间", caught_at),
            ("尺寸", f"{item['size_cm']} cm" if item["size_cm"] is not None else "未确认"),
            ("等级", f"{item['stars']} 级" if item["stars"] is not None else "未确认"),
        )
        if item["size_kind"] in ("max", "min"):
            details["facts"] += (("尺寸成就", item["size_kind"].upper()),)
        if item["new_record"]:
            details["facts"] += (("个人纪录", "新纪录"),)
        show_details(panel, details, width=150)
        if not item["fish_id"]:
            ttk.Label(
                panel,
                text=("图鉴按鱼获图像匹配" if source == "image" else "图鉴按记录名称匹配")
                if fish
                else "鱼种尚未确认，暂无对应图鉴资料。",
                style="Hint.TLabel",
                wraplength=180,
            ).pack(fill="x", pady=8)
