"""桌面界面的统一颜色、字体与控件样式。"""

import tkinter as tk
from importlib.resources import as_file, files
from tkinter import ttk

BACKGROUND = "#edf2f4"
SURFACE = "#ffffff"
INK = "#203640"
MUTED = "#627780"
ACCENT = "#087f78"
FONT = "Microsoft YaHei UI"


def apply_theme(root):
    root.configure(background=BACKGROUND)
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(FONT, 10), foreground=INK, background=SURFACE)
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
    style.configure("TCheckbutton", background=SURFACE, padding=(0, 3))
    style.map("TCheckbutton", background=[("active", SURFACE)])
    _checkmark_style(root, style)


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
