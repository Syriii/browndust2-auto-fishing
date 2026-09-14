"""桌面界面的统一颜色、字体与控件样式。"""

import tkinter as tk
from importlib.resources import as_file, files
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

BACKGROUND = "#edf2f4"
SURFACE = "#ffffff"
INK = "#203640"
MUTED = "#627780"
ACCENT = "#087f78"
LINE = "#dce5e8"
TINT = "#e2f2ef"
FONT = "微软雅黑"


def apply_theme(root):
    root.configure(background=BACKGROUND)
    # 输入框使用 Tk 命名字体，不会继承 ttk 的全局字体。
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        tkfont.nametofont(name, root=root).configure(family=FONT, size=11)
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(FONT, 11), foreground=INK, background=SURFACE)
    style.configure("TFrame", background=BACKGROUND)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("TLabel", background=SURFACE)
    style.configure("Hint.TLabel", foreground=MUTED, font=(FONT, 9))
    style.configure("Page.TLabel", background=BACKGROUND)
    style.configure("PageHint.TLabel", background=BACKGROUND, foreground=MUTED, font=(FONT, 9))
    style.configure("Title.TLabel", background=BACKGROUND, font=(FONT, 18, "bold"))
    style.configure("TLabelframe", background=SURFACE, bordercolor="#d4dfe2")
    style.configure("TLabelframe.Label", background=SURFACE, font=(FONT, 11, "bold"))
    style.configure("Section.TLabel", font=(FONT, 11, "bold"))
    style.configure("Heading.TLabel", background=BACKGROUND, font=(FONT, 17, "bold"))
    style.configure("CardTitle.TLabel", font=(FONT, 12, "bold"))
    style.configure("PageHint.TLabel", background=BACKGROUND, foreground=MUTED, font=(FONT, 10))
    style.configure("Advice.TLabel", foreground=ACCENT, font=(FONT, 9))
    style.configure("TButton", padding=(14, 8), background="#f3f7f7", bordercolor="#d4dfe2")
    style.map("TButton", background=[("active", "#e3eeed")])
    style.configure("Start.TButton", background=ACCENT, foreground="white", borderwidth=0)
    style.map(
        "Start.TButton",
        background=[("disabled", "#d6e1e2"), ("active", "#056a65")],
        foreground=[("disabled", "#7b8e94")],
    )
    style.configure("Stop.TButton", background="#b34249", foreground="white")
    style.map("Stop.TButton", background=[("disabled", "#d6e1e2"), ("active", "#94333a")])
    style.configure("TEntry", padding=6, fieldbackground=SURFACE, bordercolor="#c6d4d9")
    style.configure("TCombobox", padding=5, arrowsize=14, bordercolor="#c6d4d9")
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE)])
    style.configure("TCombobox", lightcolor=LINE, darkcolor=LINE, arrowcolor=MUTED)
    style.configure("TEntry", lightcolor=LINE, darkcolor=LINE)
    style.configure(
        "Vertical.TScrollbar",
        background="#c5d3d8",
        troughcolor=BACKGROUND,
        borderwidth=0,
        arrowsize=10,
    )
    style.layout(
        "Vertical.TScrollbar",
        [
            (
                "Vertical.Scrollbar.trough",
                {
                    "sticky": "ns",
                    "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})],
                },
            )
        ],
    )
    _rounded_styles(root, style)
    style.configure("TCheckbutton", background=SURFACE, padding=(0, 3))
    style.map("TCheckbutton", background=[("active", SURFACE)])
    _checkmark_style(root, style)


def _rounded_styles(root, style):
    """九宫格圆角底图沿用 ttk 的禁用、焦点和键盘行为。"""
    scale = root.winfo_fpixels("1i") / 96
    radius = max(6, round(7 * scale))
    size = radius * 2 + 5
    root._surface_images = images = []

    def surface(fill, border, outside=BACKGROUND):
        bitmap = Image.new("RGB", (size * 4, size * 4), outside)
        ImageDraw.Draw(bitmap).rounded_rectangle(
            (2, 2, size * 4 - 3, size * 4 - 3),
            radius=radius * 4,
            fill=fill,
            outline=border,
            width=4,
        )
        photo = ImageTk.PhotoImage(
            bitmap.resize((size, size), Image.Resampling.LANCZOS), master=root
        )
        images.append(photo)
        return photo

    palettes = {
        "TButton": (SURFACE, LINE, "#f2f8f7", TINT, INK),
        "Start.TButton": (ACCENT, ACCENT, "#096b66", "#096b66", "white"),
        "Stop.TButton": ("#b34249", "#b34249", "#94333a", "#94333a", "white"),
        "Nav.TButton": (SURFACE, SURFACE, "#f1f7f6", TINT, INK),
        "View.TButton": (SURFACE, LINE, "#f1f7f6", TINT, INK),
    }
    for name, (fill, border, hover, selected, foreground) in palettes.items():
        element = "Rounded." + name
        style.element_create(
            element,
            "image",
            surface(fill, border, SURFACE if name == "Nav.TButton" else BACKGROUND),
            ("disabled", surface("#eef2f3", LINE)),
            ("pressed", surface(selected, ACCENT if name != "Nav.TButton" else TINT)),
            ("focus", surface(fill, ACCENT)),
            ("active", surface(hover, border)),
            border=radius,
            padding=0,
            sticky="nsew",
        )
        style.layout(
            name,
            [
                (
                    element,
                    {
                        "sticky": "nsew",
                        "children": [
                            (
                                "Button.padding",
                                {
                                    "sticky": "nsew",
                                    "children": [("Button.label", {"sticky": "nsew"})],
                                },
                            )
                        ],
                    },
                )
            ],
        )
        style.configure(
            name,
            padding=(14, 9),
            foreground=foreground,
            background=fill,
            borderwidth=1,
            relief="flat",
            anchor="center",
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
        )
        style.map(
            name,
            background=[("disabled", "#eef2f3"), ("pressed", selected), ("active", hover)],
            foreground=[("disabled", "#8b9da3"), ("pressed", foreground)],
            bordercolor=[("focus", ACCENT), ("pressed", ACCENT)],
        )
    style.configure("Nav.TButton", anchor="w", padding=(14, 13))
    style.map("Nav.TButton", foreground=[("pressed", ACCENT)])
    style.configure("View.TButton", padding=9, width=0)
    style.element_create(
        "Sheet.border", "image", surface(SURFACE, LINE), border=radius, sticky="nsew"
    )
    style.layout("Sheet.TFrame", [("Sheet.border", {"sticky": "nsew"})])
    style.configure("Sheet.TFrame", background=BACKGROUND)


def _checkmark_style(root, style):
    """替换 clam 的叉号图元，保留 ttk 原生状态和键盘交互。"""
    scale = root.winfo_fpixels("1i") / 96
    size = max(16, round(18 * scale))
    images = []
    for selected, disabled in ((False, False), (True, False), (False, True), (True, True)):
        image = tk.PhotoImage(master=root, width=size + round(6 * scale), height=size)
        border = "#aab8bd" if disabled else ACCENT if selected else "#7b8e94"
        fill = border if selected else "#f2f5f5" if disabled else SURFACE
        image.put(border, to=(0, 0, size, size))
        image.put(fill, to=(1, 1, size - 1, size - 1))
        if selected:
            # 两条相连线段构成 ✓，所有 DPI 都按相同比例绘制。
            for start, end in (((0.22, 0.50), (0.43, 0.72)), ((0.43, 0.72), (0.80, 0.27))):
                for step in range(size * 2):
                    t = step / (size * 2 - 1)
                    x = round((start[0] + (end[0] - start[0]) * t) * size)
                    y = round((start[1] + (end[1] - start[1]) * t) * size)
                    radius = max(1, round(scale))
                    image.put("white", to=(x - radius, y - radius, x + radius, y + radius))
        images.append(image)
    root._checkbox_images = images
    if "Tick.indicator" not in style.element_names():
        style.element_create(
            "Tick.indicator",
            "image",
            images[0],
            ("disabled", "selected", images[3]),
            ("disabled", images[2]),
            ("selected", images[1]),
        )
    style.layout(
        "TCheckbutton",
        [
            (
                "Checkbutton.padding",
                {
                    "sticky": "nswe",
                    "children": [
                        ("Tick.indicator", {"side": "left", "sticky": ""}),
                        (
                            "Checkbutton.focus",
                            {
                                "side": "left",
                                "sticky": "w",
                                "children": [("Checkbutton.label", {"sticky": "nswe"})],
                            },
                        ),
                    ],
                },
            )
        ],
    )


def apply_icon(root):
    resources = files("bd2_fishing").joinpath("resources/icons")
    with as_file(resources.joinpath("app.ico")) as icon:
        root.iconbitmap(default=str(icon))
    with as_file(resources.joinpath("app-64.png")) as icon:
        return tk.PhotoImage(master=root, file=str(icon))


def center_window(window, services, parent=None):
    """布局完成后定位自身窗口；原生显示器操作通过应用服务执行。"""
    window.update_idletasks()

    def position(event=None):
        if event is not None and event.widget is not window:
            return
        if window.winfo_viewable():
            if binding is not None:
                window.unbind("<Map>", binding)
            handle = window.winfo_id()
            parent_handle = parent.winfo_id() if parent else None
            # Tk 的最小客户区不能超过工作区，否则原生居中缩窗会被最小尺寸反向撑大。
            limit = services.desktop_client_size_limit(handle, parent_handle)
            window.minsize(*(min(size, cap) for size, cap in zip(window.minsize(), limit)))
            window.update_idletasks()
            services.center_desktop_window(handle, parent_handle)

    binding = None
    if window.winfo_viewable():
        position()
    else:
        binding = window.bind("<Map>", position, add="+")
