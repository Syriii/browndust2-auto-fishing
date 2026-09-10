"""设置表单的滚动容器；大字体或短屏幕下仍可访问全部字段。"""

import tkinter as tk
from tkinter import ttk

from bd2_fishing.ui.theme import SURFACE


class ScrollablePage(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="Card.TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=SURFACE, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.body = ttk.Frame(self.canvas, padding=20, style="Card.TFrame")
        self.item = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self._layout)
        self.body.bind("<Configure>", self._layout)
        self.winfo_toplevel().bind("<MouseWheel>", self._wheel, add="+")

    def _layout(self, event=None):
        width = self.canvas.winfo_width()
        height = max(self.canvas.winfo_height(), self.body.winfo_reqheight())
        self.canvas.itemconfigure(self.item, width=width, height=height)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        if height > self.canvas.winfo_height():
            self.scrollbar.grid(row=0, column=1, sticky="ns")
        else:
            self.scrollbar.grid_remove()
            self.canvas.yview_moveto(0)
        for widget in self.body.winfo_children():
            if isinstance(widget, ttk.Label):
                current = int(widget.cget("wraplength") or 0)
                desired = max(200, width - 40)
                if current > 0 and current != desired:
                    widget.configure(wraplength=desired)

    def _wheel(self, event):
        if not self.winfo_viewable() or isinstance(event.widget, ttk.Combobox):
            return
        widget = event.widget
        while widget is not None and widget is not self:
            widget = getattr(widget, "master", None)
        if widget is self and self.body.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"
