"""日志旁的本次鱼获，按启动轮次过滤，停止后保留到下次开始。"""

from tkinter import ttk

from bd2_fishing.ui.collection_widgets import FishPhotos
from bd2_fishing.ui.fish_tile import FishTile
from bd2_fishing.ui.scrolling import ScrollablePage


class SessionCatches(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, style="Sheet.TFrame", padding=8)
        self.app = app
        self.service = app.services.fish_catalogue_service()
        self.photos = FishPhotos(self.service, self, crop=False)
        self._key = None
        self.tiles = {}
        self.configure(width=round(250 * self.photos.scale))
        self.grid_propagate(False)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = ttk.Frame(self, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.heading = ttk.Label(header, text="本次鱼获 · 0", style="Section.TLabel")
        self.heading.pack(side="left")
        ttk.Button(header, text="全部 ›", style="Compact.TButton", command=self.open_history).pack(
            side="right"
        )
        self.scroll = ScrollablePage(self, padding=0, surface=True)
        self.scroll.configure(style="Card.TFrame", padding=0)
        self.scroll.grid(row=1, column=0, sticky="nsew")

    def refresh(self):
        collection = self.app.collection
        key = collection.run_id, collection.journal.revision
        if key == self._key:
            return
        self._key = key
        rows = (
            collection.journal.history(limit=30, run_id=collection.run_id)
            if collection.run_id
            else []
        )
        count = collection.journal.run_count(collection.run_id) if collection.run_id else 0
        self.heading.configure(text=f"本次鱼获 · {count}")
        visible = {item["id"] for item in rows}
        for identity in tuple(self.tiles):
            if identity not in visible:
                self.tiles.pop(identity).destroy()
        for widget in self.scroll.body.winfo_children():
            if not isinstance(widget, FishTile):
                widget.destroy()
        for col in range(4):
            self.scroll.body.columnconfigure(col, weight=1, uniform="session-fish")
        if not rows:
            ttk.Label(self.scroll.body, text="本次还没有鱼获", style="Hint.TLabel").grid(
                row=0, column=0, columnspan=4, pady=12
            )
        for index, item in enumerate(rows):
            if item["id"] not in self.tiles:
                self._tile(item, index)
            self.tiles[item["id"]].grid(
                row=index // 4, column=index % 4, sticky="ew", padx=1, pady=1
            )
        self.scroll.refresh()
        self.scroll.canvas.yview_moveto(0)

    def _tile(self, item, index):
        fish = self.service.catch_reference(item)
        if fish is None:
            fish = self.service.catch_image_reference(
                self.app.collection.journal.evidence(item["id"]), item["location"]
            )
        name = fish.name if fish else self.service.catch_name(item["name"])
        tile = FishTile(
            self.scroll.body,
            photo=lambda size, f=fish: self.photos.get(f.id, size) if f else None,
            name=name,
            subtitle=name,
            command=lambda: self.open_history(item["id"]),
            view="compact",
            colorful=item["rarity"] == "legendary",
            rank=item["stars"],
            measurement=f"{item['size_cm']:g}cm" if item["size_cm"] is not None else "尺寸未确认",
            marker=item["size_kind"].upper() if item["size_kind"] in ("max", "min") else "",
        )
        self.tiles[item["id"]] = tile

    def open_history(self, identity=None):
        page = self.app.catches_page
        page.category = "all"
        page.day.set("全部日期")
        if identity is not None:
            page.expanded = identity
        self.app.show_page("catches")
