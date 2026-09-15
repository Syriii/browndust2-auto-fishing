"""设置表单的滚动容器；大字体或短屏幕下仍可访问全部字段。"""

import tkinter as tk
from tkinter import ttk

from bd2_fishing.ui.theme import BACKGROUND, SURFACE


class ScrollablePage(ttk.Frame):
    def __init__(self, parent, *, padding=20, surface=False):
        super().__init__(
            parent, style="Sheet.TFrame" if surface else "TFrame", padding=1 if surface else 0
        )
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self,
            background=SURFACE if surface else BACKGROUND,
            highlightthickness=0,
            width=1,
            height=1,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self._scrolled)
        self.body = ttk.Frame(
            self.canvas, padding=padding, style="Card.TFrame" if surface else "TFrame"
        )
        self.item = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self._wheel_delta = 0
        self._layout_key = None
        self._viewport_key = None
        self._refresh_id = None
        self._viewport_id = None
        self.canvas.bind("<Configure>", self._layout)
        self.body.bind("<Configure>", self._layout)
        self._wheel_owner = self.winfo_toplevel()
        self._wheel_binding = self._wheel_owner.bind("<MouseWheel>", self._wheel, add="+")

    def _scrolled(self, first, last):
        self.scrollbar.set(first, last)
        key = first, last, self.canvas.winfo_width(), self.canvas.winfo_height()
        if key != self._viewport_key:
            self._viewport_key = key
            if self._viewport_id is None:
                self._viewport_id = self.after_idle(self._notify_viewport)

    def _notify_viewport(self):
        self._viewport_id = None
        self.canvas.event_generate("<<ViewportChanged>>", when="tail")

    def refresh(self):
        """合并本轮变更，避免在点击回调中嵌套刷新整个窗口。"""
        if self._refresh_id is None:
            self._refresh_id = self.after_idle(self._refresh_layout)

    def _refresh_layout(self):
        self._refresh_id = None
        self._layout()

    def destroy(self):
        for callback in (self._refresh_id, self._viewport_id):
            if callback is not None:
                self.after_cancel(callback)
        self._wheel_owner.unbind("<MouseWheel>", self._wheel_binding)
        super().destroy()

    def _layout(self, event=None):
        width = self.canvas.winfo_width()
        height = max(self.canvas.winfo_height(), self.body.winfo_reqheight())
        key = width, height, self.canvas.winfo_height()
        if key == self._layout_key:
            return
        self._layout_key = key
        self.canvas.itemconfigure(self.item, width=width, height=height)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        if height <= self.canvas.winfo_height():
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
            self._wheel_delta += event.delta
            steps = int(self._wheel_delta / 120)
            self._wheel_delta -= steps * 120
            if steps:
                self.canvas.yview_scroll(-steps, "units")
            return "break"
