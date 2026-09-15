"""桌面界面的统一颜色、字体与控件样式。"""

import tkinter as tk
from importlib.resources import as_file, files
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

BACKGROUND = "#eef0f5"
SURFACE = "#fafbfd"
INK = "#1d1d1f"
MUTED = "#6e6e73"
ACCENT = "#007aff"
LINE = "#d9dde5"
TINT = "#e5efff"
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
    style.configure("TLabelframe", background=SURFACE, bordercolor="#d9dde5")
    style.configure("TLabelframe.Label", background=SURFACE, font=(FONT, 11, "bold"))
    style.configure("Section.TLabel", font=(FONT, 11, "bold"))
    style.configure("Heading.TLabel", background=BACKGROUND, font=(FONT, 17, "bold"))
    style.configure("CardTitle.TLabel", font=(FONT, 12, "bold"))
    style.configure("PageHint.TLabel", background=BACKGROUND, foreground=MUTED, font=(FONT, 10))
    style.configure("Advice.TLabel", foreground=ACCENT, font=(FONT, 9))
    style.configure("TButton", padding=(14, 8), background="#f6f7fa", bordercolor="#d9dde5")
    style.map("TButton", background=[("active", "#e8edf5")])
    style.configure("Start.TButton", background=ACCENT, foreground="white", borderwidth=0)
    style.map(
        "Start.TButton",
        background=[("disabled", "#e5e5ea"), ("active", "#0062cc")],
        foreground=[("disabled", "#8e8e93")],
    )
    style.configure("Stop.TButton", background="#d93b40", foreground="white")
    style.map("Stop.TButton", background=[("disabled", "#e5e5ea"), ("active", "#b92e33")])
    style.configure("TEntry", padding=6, fieldbackground=SURFACE, bordercolor="#c8ccd4")
    _combobox_style(root, style)
    style.configure("TEntry", lightcolor=LINE, darkcolor=LINE)
    style.configure(
        "Vertical.TScrollbar",
        background="#b8bdc8",
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
    style.configure("Compact.TButton", padding=(6, 3), font=(FONT, 9))
    style.configure("TCheckbutton", background=SURFACE, padding=(0, 3))
    style.map("TCheckbutton", background=[("active", SURFACE)])
    _checkmark_style(root, style)
    style.configure(
        "Draft.Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=INK,
        borderwidth=0,
        rowheight=round(34 * root.winfo_fpixels("1i") / 96),
    )
    style.configure(
        "Draft.Treeview.Heading",
        background=SURFACE,
        foreground=MUTED,
        font=(FONT, 9),
        relief="flat",
    )
    style.map("Draft.Treeview", background=[("selected", TINT)], foreground=[("selected", INK)])


def _combobox_style(root, style):
    """统一下拉框的焦点配色与箭头，继续使用 ttk 原生弹出和键盘行为。"""
    scale = root.winfo_fpixels("1i") / 96
    images = []
    for color in (MUTED, ACCENT, "#aeaeb2"):
        width, height = round(28 * scale), round(18 * scale)
        bitmap = Image.new("RGBA", (width * 4, height * 4))
        ImageDraw.Draw(bitmap).line(
            [
                (round(x * width * 4), round(y * height * 4))
                for x, y in ((0.32, 0.4), (0.5, 0.65), (0.68, 0.4))
            ],
            fill=color,
            width=max(4, round(6 * scale)),
            joint="curve",
        )
        images.append(
            ImageTk.PhotoImage(
                bitmap.resize((width, height), Image.Resampling.LANCZOS), master=root
            )
        )
    root._combobox_images = images
    style.element_create("Select.field", "from", "clam", "Entry.field")
    style.element_create(
        "Select.downarrow",
        "image",
        images[0],
        ("disabled", images[2]),
        ("active", images[1]),
        ("focus", images[1]),
    )
    style.layout(
        "TCombobox",
        [
            (
                "Select.field",
                {
                    "sticky": "nsew",
                    "children": [
                        ("Select.downarrow", {"side": "right", "sticky": ""}),
                        (
                            "Combobox.padding",
                            {
                                "sticky": "nsew",
                                "children": [
                                    ("Combobox.textarea", {"sticky": "nsew"}),
                                ],
                            },
                        ),
                    ],
                },
            ),
        ],
    )
    style.configure(
        "TCombobox",
        padding=(8, 5),
        bordercolor=LINE,
        lightcolor=SURFACE,
        darkcolor=SURFACE,
        fieldbackground=SURFACE,
        foreground=INK,
        selectbackground=TINT,
        selectforeground=INK,
    )
    # clam 的 readonly+focus 默认是白字，必须与自定义白底同时覆盖。
    style.map(
        "TCombobox",
        foreground=[("disabled", MUTED), ("readonly", INK)],
        fieldbackground=[("disabled", "#f2f2f7"), ("readonly", SURFACE)],
        background=[("disabled", "#f2f2f7"), ("!disabled", SURFACE)],
        bordercolor=[("disabled", LINE), ("focus", ACCENT), ("active", "#b4c8e8")],
        selectforeground=[("disabled", MUTED), ("!disabled", INK)],
        selectbackground=[("disabled", "#f2f2f7"), ("!disabled", TINT)],
    )
    for option, value in {
        "background": SURFACE,
        "foreground": INK,
        "selectBackground": TINT,
        "selectForeground": INK,
        "relief": "flat",
        "borderWidth": 0,
    }.items():
        root.option_add(f"*TCombobox*Listbox.{option}", value)


def _rounded_styles(root, style):
    """九宫格圆角底图沿用 ttk 的禁用、焦点和键盘行为。"""
    scale = root.winfo_fpixels("1i") / 96
    radius = max(8, round(10 * scale))
    # Tk 平铺中心而非拉伸。5px 中心铺满大面板会产生数万次原生绘图。
    # 宽高设为 0，让底图不参与控件最小尺寸计算。
    size = radius * 2 + 128
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
        if fill == SURFACE:
            draw = ImageDraw.Draw(bitmap)
            draw.rounded_rectangle(
                (6, 6, size * 4 - 7, size * 4 - 7),
                radius=max(1, radius * 4 - 4),
                outline="#ffffff",
                width=4,
            )
        photo = ImageTk.PhotoImage(
            bitmap.resize((size, size), Image.Resampling.LANCZOS), master=root
        )
        images.append(photo)
        return photo

    palettes = {
        "TButton": (SURFACE, LINE, "#f0f3f9", TINT, INK),
        "Start.TButton": (ACCENT, ACCENT, "#0062cc", "#0062cc", "white"),
        "Stop.TButton": ("#d93b40", "#d93b40", "#b92e33", "#b92e33", "white"),
        "Nav.TButton": (SURFACE, SURFACE, "#f0f3f9", TINT, INK),
        "View.TButton": (SURFACE, LINE, "#f0f3f9", TINT, INK),
    }
    for name, (fill, border, hover, selected, foreground) in palettes.items():
        element = "Rounded." + name
        style.element_create(
            element,
            "image",
            surface(fill, border, SURFACE if name == "Nav.TButton" else BACKGROUND),
            ("disabled", surface("#f2f2f7", LINE)),
            ("pressed", surface(selected, ACCENT if name != "Nav.TButton" else TINT)),
            ("focus", surface(fill, ACCENT)),
            ("active", surface(hover, border)),
            border=radius,
            width=0,
            height=0,
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
            background=[("disabled", "#f2f2f7"), ("pressed", selected), ("active", hover)],
            foreground=[("disabled", "#8e8e93"), ("pressed", foreground)],
            bordercolor=[("focus", ACCENT), ("pressed", ACCENT)],
        )
    style.configure("Nav.TButton", anchor="w", padding=(14, 13))
    style.map("Nav.TButton", foreground=[("pressed", ACCENT)])
    style.configure("View.TButton", padding=9, width=0)
    style.element_create(
        "Sheet.border",
        "image",
        surface(SURFACE, LINE),
        border=radius,
        width=0,
        height=0,
        sticky="nsew",
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
        border = "#c7c7cc" if disabled else ACCENT if selected else "#8e8e93"
        fill = border if selected else "#f2f2f7" if disabled else SURFACE
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
