"""图鉴与鱼获共用的鱼图、详情和视图按钮。"""

import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from bd2_fishing.ui.theme import ACCENT, FONT


class FishPhotos:
    def __init__(self, service, master):
        self.service, self.master = service, master
        self.cache = {}

    def get(self, identity, size=(130, 84)):
        key = identity, size
        if key not in self.cache:
            try:
                self.cache[key] = ImageTk.PhotoImage(
                    self.service.picture(identity, size), master=self.master
                )
            except (OSError, KeyError):
                self.cache[key] = None
        return self.cache[key]


class ViewButtons(ttk.Frame):
    def __init__(self, parent, command):
        super().__init__(parent, style="Card.TFrame")
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
            button = ttk.Button(self, image=icon, command=lambda v=view: command(v), width=3)
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


def show_facts(parent, service, identity, width=450):
    details = service.details(identity)
    facts = ttk.Frame(parent, style="Card.TFrame")
    facts.pack(fill="x", padx=12, pady=8)
    facts.columnconfigure(1, weight=1)
    for row, (label, value) in enumerate(details["facts"]):
        ttk.Label(facts, text=label, style="Hint.TLabel", width=8).grid(
            row=row, column=0, sticky="nw", pady=4
        )
        ttk.Label(facts, text=value, wraplength=width, justify="left").grid(
            row=row, column=1, sticky="nw", pady=4
        )
    for name, text in details["mechanisms"]:
        ttk.Label(parent, text=name, font=(FONT, 10, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        ttk.Label(parent, text=text, wraplength=width, justify="left").pack(
            fill="x", padx=12, pady=(0, 6)
        )


def clear_children(parent):
    for child in parent.winfo_children():
        child.destroy()
