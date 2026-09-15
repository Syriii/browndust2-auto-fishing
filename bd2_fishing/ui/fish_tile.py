"""鱼卡的图片、名称和状态独立排版，浏览与选择共用同一个入口。"""

import tkinter as tk

from bd2_fishing.ui.theme import ACCENT, BACKGROUND, FONT, INK, LINE, MUTED, SURFACE, TINT


class FishTile(tk.Canvas):
    def __init__(
        self,
        parent,
        *,
        photo,
        name,
        subtitle,
        command,
        view="grid",
        selected=False,
        badge="",
        colorful=False,
        rank=None,
        footnote="",
        measurement="",
        marker="",
    ):
        self.scale = parent.winfo_fpixels("1i") / 96
        self.is_list = view == "list"
        self.is_icon = view == "icons"
        super().__init__(
            parent,
            background=BACKGROUND,
            highlightthickness=0,
            bd=0,
            width=round((64 if self.is_icon else 140) * self.scale),
            height=round(
                (
                    90
                    if self.is_icon and footnote
                    else 72
                    if self.is_icon
                    else 78
                    if self.is_list
                    else 159
                )
                * self.scale
            ),
            takefocus=True,
            cursor="hand2",
        )
        self.photo_provider, self.command = photo, command
        self.name, self.subtitle, self.badge = name, subtitle, badge
        self.selected, self.colorful, self.hover = selected, colorful, False
        self.rank = rank
        self.footnote, self.measurement, self.marker = footnote, measurement, marker
        self.photo = None
        self._draw_key = None
        self.viewport = parent
        while self.viewport is not None and not isinstance(self.viewport, tk.Canvas):
            self.viewport = self.viewport.master
        self._viewport_binding = (
            self.viewport.bind("<<ViewportChanged>>", self.draw, add="+")
            if self.viewport is not None
            else None
        )
        self._pointer_down = False
        self.bind("<Configure>", self.draw)
        self.bind("<Expose>", self.draw)
        self.bind("<Enter>", lambda _: self._hover(True))
        self.bind("<Leave>", lambda _: self._hover(False))
        self.bind("<FocusIn>", self.draw)
        self.bind("<FocusOut>", self.draw)
        self.bind("<Button-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Return>", self._activate)
        self.bind("<space>", self._activate)

    def destroy(self):
        if self._viewport_binding:
            self.viewport.unbind("<<ViewportChanged>>", self._viewport_binding)
            self._viewport_binding = None
        super().destroy()

    def _hover(self, active):
        self.hover = active
        self.draw()

    def _activate(self, event):
        self.focus_set()
        self.command()
        return "break"

    def _press(self, event):
        self.focus_set()
        self._pointer_down = True

    def _release(self, event):
        pressed, self._pointer_down = self._pointer_down, False
        if pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            return self._activate(event)

    def draw(self, event=None):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 10 or not self.winfo_ismapped() or not self._visible(height):
            return
        key = width, height, self.selected, self.hover, self.focus_get() is self, self.badge
        if key == self._draw_key:
            return
        self.delete("all")
        self._background(width, height)
        self._content(width, height)
        self._draw_key = key

    def _visible(self, height):
        if self.viewport is None:
            return True
        # 滚动容器 body 的原生坐标可能包含 Tk 的屏外偏移，使用 Canvas 视口坐标。
        top = self.winfo_y() - self.viewport.canvasy(0)
        parent = self.master
        while parent.master is not self.viewport:
            top += parent.winfo_y()
            parent = parent.master
        return top < self.viewport.winfo_height() and top + height > 0

    def _background(self, width, height):
        s = self.scale
        radius = 8 * s
        edge = ACCENT if self.selected or self.focus_get() is self else LINE
        fill = TINT if self.selected else "#f5faf9" if self.hover else SURFACE
        self.create_polygon(
            1,
            radius,
            1,
            1,
            radius,
            1,
            width - radius,
            1,
            width - 1,
            1,
            width - 1,
            radius,
            width - 1,
            height - radius,
            width - 1,
            height - 1,
            width - radius,
            height - 1,
            radius,
            height - 1,
            1,
            height - 1,
            1,
            height - radius,
            smooth=True,
            splinesteps=24,
            fill=fill,
            outline=edge,
            width=2 if self.selected or self.focus_get() is self else 1,
        )

    def _content(self, width, height):
        s = self.scale
        if self.is_icon:
            self._icon_content(width, height)
            return
        if self.is_list:
            picture_size = (round(88 * s), round(56 * s))
            image_x, image_y = 10 * s, 11 * s
            text_x, text_y = 111 * s, 18 * s
        else:
            picture_size = (max(30, width - round(12 * s)), round(91 * s))
            image_x, image_y = 6 * s, 6 * s
            text_x, text_y = 11 * s, 104 * s
        self.photo = self.photo_provider(picture_size)
        if self.photo:
            self.create_image(image_x, image_y, image=self.photo, anchor="nw")
        self.create_text(
            text_x,
            text_y,
            text=self.name,
            anchor="nw",
            fill=INK,
            font=(FONT, 11),
            width=max(50, width - text_x - 10 * s),
        )
        self.create_text(
            text_x,
            text_y + 25 * s,
            text=self.subtitle,
            anchor="nw",
            fill="#705394" if self.colorful else MUTED,
            font=(FONT, 9),
        )
        self._marks(width, height)

    def _icon_content(self, width, height):
        s = self.scale
        edge = max(20, round(min(width - 10 * s, 62 * s)))
        self.photo = self.photo_provider((edge, edge))
        if self.photo:
            self.create_image(width / 2, 36 * s, image=self.photo)
        else:
            self.create_text(width / 2, 36 * s, text="?", fill=MUTED, font=(FONT, 18))
        if self.measurement:
            self.create_rectangle(3 * s, 51 * s, width - 3 * s, 67 * s, fill="#e5efee", outline="")
            self.create_text(width / 2, 59 * s, text=self.measurement, fill=INK, font=(FONT, 8))
        if self.footnote:
            self.create_text(width / 2, 79 * s, text=self.footnote, fill=MUTED, font=(FONT, 8))
        if self.marker:
            self.create_rectangle(3 * s, 3 * s, 31 * s, 17 * s, fill=ACCENT, outline="")
            self.create_text(17 * s, 10 * s, text=self.marker, fill="white", font=(FONT, 8))
        if self.rank in (1, 2, 3):
            color = {1: "#65aa70", 2: "#5f9dd4", 3: "#a879bd"}[self.rank]
            for index in range(self.rank):
                x = width - (8 + index * 7) * s
                self.create_oval(x - 4 * s, 5 * s, x, 9 * s, fill=color, outline=color)
        if self.badge:
            self.create_text(7 * s, height - 7 * s, text="✓", anchor="sw", fill=ACCENT)

    def _marks(self, width, height):
        s = self.scale
        if self.badge:
            self.create_rectangle(
                width - 50 * s, 10 * s, width - 8 * s, 34 * s, fill=ACCENT, outline=ACCENT
            )
            self.create_text(
                width - 13 * s,
                16 * s,
                text=self.badge,
                anchor="ne",
                fill="white",
                font=(FONT, 10, "bold"),
            )
        elif self.is_list:
            self.create_text(
                width - 20 * s,
                height / 2,
                text="›",
                fill=MUTED,
                font=(FONT, 13),
            )
        if self.colorful and not self.is_list:
            self.create_line(
                10 * s, height - 2 * s, width - 10 * s, height - 2 * s, fill="#a88ec5", width=3 * s
            )
