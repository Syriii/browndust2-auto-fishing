"""图鉴与鱼获共用的鱼图、详情和视图按钮。"""

import tkinter as tk
from collections import OrderedDict
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk

from bd2_fishing.ui.theme import ACCENT, FONT


def gallery_columns(width, scale):
    return max(2, min(12, max(1, width) // round(72 * scale)))


class FishPhotos:
    def __init__(self, service, master, *, crop=True):
        self.service, self.master = service, master
        self.crop = crop
        self.cache = OrderedDict()
        self.scale = master.winfo_fpixels("1i") / 96

    def get(self, identity, size=(130, 84)):
        key = identity, size
        if key not in self.cache:
            try:
                original = self.service.picture(identity, (size[0] * 2, size[1] * 2))
                picture = (
                    ImageOps.fit(original, size)
                    if self.crop
                    else ImageOps.pad(
                        original, size, method=Image.Resampling.LANCZOS, color="#f5f8fa"
                    )
                )
                self.cache[key] = ImageTk.PhotoImage(
                    picture,
                    master=self.master,
                )
            except (OSError, KeyError):
                self.cache[key] = None
        self.cache.move_to_end(key)
        while len(self.cache) > 384:
            self.cache.popitem(last=False)
        return self.cache[key]


class ViewButtons(ttk.Frame):
    def __init__(self, parent, command):
        super().__init__(parent, style="TFrame")
        self.buttons, self.images = {}, []
        self.tip = None
        for index, (view, label) in enumerate((("grid", "网格视图"), ("list", "列表视图"))):
            icon = tk.PhotoImage(master=self, width=18, height=18)
            if view == "grid":
                for x in (2, 10):
                    for y in (2, 10):
                        icon.put(ACCENT, to=(x, y, x + 6, y + 6))
                        icon.put("white", to=(x + 1, y + 1, x + 5, y + 5))
            else:
                for y in (3, 8, 13):
                    icon.put(ACCENT, to=(2, y, 4, y + 2))
                    icon.put(ACCENT, to=(6, y, 17, y + 2))
            self.images.append(icon)
            button = ttk.Button(
                self, image=icon, command=lambda v=view: command(v), style="View.TButton"
            )
            button.grid(row=0, column=index, padx=3)
            button.bind("<Enter>", lambda event, text=label: self._tip(event.widget, text))
            button.bind("<Leave>", lambda _: self._hide())
            button.bind("<FocusOut>", lambda _: self._hide())
            self.buttons[view] = button
        self.bind("<Destroy>", lambda _: self._hide())

    def _tip(self, button, text):
        self._hide()
        self.tip = tk.Toplevel(self)
        self.tip.overrideredirect(True)
        self.tip.geometry(f"+{button.winfo_rootx()}+{button.winfo_rooty() + button.winfo_height()}")
        ttk.Label(self.tip, text=text, padding=5).pack()

    def _hide(self):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None

    def select(self, view):
        for name, button in self.buttons.items():
            button.state(["pressed"] if name == view else ["!pressed"])


class FishDetails(ttk.Frame):
    """详情控件保留，只替换文字和图片；选鱼不清空侧栏。"""

    def __init__(self, parent):
        super().__init__(parent, style="Card.TFrame")
        self.title = ttk.Label(self, style="Section.TLabel")
        self.title.pack(anchor="w")
        self.picture = ttk.Label(self)
        self.picture.pack(pady=8)
        self.facts = ttk.Frame(self, style="Card.TFrame")
        self.facts.pack(fill="x", padx=12, pady=8)
        self.facts.columnconfigure(1, weight=1)
        self.fields = {}
        self.mechanisms = ttk.Frame(self, style="Card.TFrame")
        self.mechanisms.pack(fill="x")
        self.mechanism_rows = {}
        self.note = ttk.Label(self, style="Hint.TLabel", wraplength=180)
        self.photo = None

    def show(self, name, photo, details, *, note=""):
        self.title.configure(text=name)
        self.photo = photo
        self.picture.configure(image=photo or "", text="" if photo else "暂无对应图片")
        wanted = dict(details["facts"])
        for label, widgets in self.fields.items():
            if label not in wanted:
                for widget in widgets:
                    widget.grid_remove()
        for row, (label, value) in enumerate(wanted.items()):
            if label not in self.fields:
                key = ttk.Label(self.facts, text=label, style="Hint.TLabel", width=8)
                content = ttk.Label(self.facts, wraplength=150, justify="left")
                content.bind("<Configure>", self._wrap)
                self.fields[label] = key, content
            key, content = self.fields[label]
            key.grid(row=row, column=0, sticky="nw", pady=4)
            content.configure(text=value)
            content.grid(row=row, column=1, sticky="new", pady=4)
        self._show_mechanisms(details["mechanisms"])
        self.note.configure(text=note)
        if note:
            self.note.pack(fill="x", pady=8)
        else:
            self.note.pack_forget()

    @staticmethod
    def _wrap(event):
        event.widget.configure(wraplength=max(40, event.width))

    def _show_mechanisms(self, mechanisms):
        wanted = dict(mechanisms)
        for name, widgets in self.mechanism_rows.items():
            if name not in wanted:
                for widget in widgets:
                    widget.pack_forget()
        for name, text in mechanisms:
            if name not in self.mechanism_rows:
                title = ttk.Label(self.mechanisms, text=name, font=(FONT, 10, "bold"))
                body = ttk.Label(self.mechanisms, wraplength=180, justify="left")
                self.mechanism_rows[name] = title, body
            title, body = self.mechanism_rows[name]
            title.pack(anchor="w", padx=12, pady=(8, 2))
            body.configure(text=text)
            body.pack(fill="x", padx=12, pady=(0, 6))


def show_facts(parent, service, identity, width=450, inset=12):
    details = service.details(identity)
    show_details(parent, details, width=width, inset=inset)


def show_details(parent, details, width=450, inset=12):
    facts = ttk.Frame(parent, style="Card.TFrame")
    facts.pack(fill="x", padx=inset, pady=8)
    facts.columnconfigure(1, weight=1)
    for row, (label, value) in enumerate(details["facts"]):
        ttk.Label(facts, text=label, style="Hint.TLabel", width=8).grid(
            row=row, column=0, sticky="nw", pady=4
        )
        value_label = ttk.Label(facts, text=value, wraplength=width, justify="left")
        value_label.grid(row=row, column=1, sticky="new", pady=4)
        value_label.bind(
            "<Configure>", lambda event: event.widget.configure(wraplength=max(40, event.width))
        )
    for name, text in details["mechanisms"]:
        ttk.Label(parent, text=name, font=(FONT, 10, "bold")).pack(
            anchor="w", padx=inset, pady=(8, 2)
        )
        ttk.Label(parent, text=text, wraplength=width, justify="left").pack(
            fill="x", padx=inset, pady=(0, 6)
        )


def clear_children(parent):
    for child in parent.winfo_children():
        child.destroy()
