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
    ):
        self.scale = parent.winfo_fpixels("1i") / 96
        self.is_list = view == "list"
        super().__init__(
            parent,
            background=BACKGROUND,
            highlightthickness=0,
            bd=0,
            width=round(140 * self.scale),
            height=round((78 if self.is_list else 159) * self.scale),
            takefocus=True,
            cursor="hand2",
        )
        self.photo_provider, self.command = photo, command
        self.name, self.subtitle, self.badge = name, subtitle, badge
        self.selected, self.colorful, self.hover = selected, colorful, False
        self.photo = None
        self._pointer_down = False
        self.bind("<Configure>", self._draw)
        self.bind("<Enter>", lambda _: self._hover(True))
        self.bind("<Leave>", lambda _: self._hover(False))
        self.bind("<FocusIn>", self._draw)
        self.bind("<FocusOut>", self._draw)
        self.bind("<Button-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Return>", self._activate)
        self.bind("<space>", self._activate)

    def _hover(self, active):
        self.hover = active
        self._draw()

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

    def _draw(self, event=None):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 10:
            return
        self._background(width, height)
        self._content(width, height)

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
                text="⌃" if self.selected else "⌄",
                fill=MUTED,
                font=(FONT, 13),
            )
        if self.colorful and not self.is_list:
            self.create_line(
                10 * s, height - 2 * s, width - 10 * s, height - 2 * s, fill="#a88ec5", width=3 * s
            )
