"""主窗口布局，页面尺寸受固定内容区约束。"""

import tkinter as tk
from tkinter import ttk

from bd2_fishing.ui.catalogue_page import CataloguePage
from bd2_fishing.ui.collection_pages import CatchesPage, TargetsPage
from bd2_fishing.ui.icons import navigation_icon
from bd2_fishing.ui.preferences import PreferencesPage
from bd2_fishing.ui.theme import ACCENT, FONT, apply_icon, apply_theme, center_window


def build_workspace(app, locations):
    root = app.root
    root.title("BD2 自动钓鱼" + (" · 界面验证" if app.preview else ""))
    scale = root.winfo_fpixels("1i") / 96
    root.geometry(f"{round(1100 * scale)}x{round(760 * scale)}")
    root.minsize(round(960 * scale), round(640 * scale))
    apply_theme(root)
    ttk.Style(root).configure("FishList.TButton", anchor="w", padding=(10, 6))
    app.brand_icon = apply_icon(root)
    root.rowconfigure(1, weight=1)
    root.columnconfigure(0, weight=1)
    brand = ttk.Frame(root, style="Card.TFrame", padding=(20, 12))
    brand.grid(row=0, column=0, sticky="ew")
    app.header_icon = app.brand_icon.subsample(2)
    ttk.Label(
        brand,
        image=app.header_icon,
        text="  BD2 自动钓鱼",
        compound="left",
        style="CardTitle.TLabel",
    ).pack(side="left")
    ttk.Label(
        brand, text="界面预览" if app.preview else "钓鱼 · 图鉴 · 鱼获", style="Hint.TLabel"
    ).pack(side="right")
    outer = ttk.Frame(root)
    outer.grid(row=1, column=0, sticky="nsew")
    outer.rowconfigure(0, weight=1)
    outer.columnconfigure(1, weight=1)
    nav = ttk.Frame(outer, width=round(146 * scale), padding=(10, 18), style="Card.TFrame")
    nav.grid(row=0, column=0, sticky="ns", padx=(0, 1))
    nav.pack_propagate(False)
    app.nav_buttons = {}
    app.nav_icons = {
        key: navigation_icon(root, key)
        for key in ("run", "catalogue", "targets", "catches", "settings")
    }
    for key, title in (
        ("run", "钓鱼"),
        ("catalogue", "图鉴"),
        ("targets", "目标"),
        ("catches", "鱼获"),
    ):
        button = ttk.Button(
            nav,
            text="  " + title,
            image=app.nav_icons[key],
            compound="left",
            style="Nav.TButton",
            command=lambda page=key: app.show_page(page),
        )
        button.pack(fill="x", pady=5)
        app.nav_buttons[key] = button
    spacer = ttk.Frame(nav, style="Card.TFrame")
    spacer.pack(fill="both", expand=True)
    app.preferences_button = ttk.Button(
        nav,
        text="  设置",
        image=app.nav_icons["settings"],
        compound="left",
        style="Nav.TButton",
        command=app.open_preferences,
    )
    app.preferences_button.pack(fill="x", pady=5)
    app.nav_buttons["settings"] = app.preferences_button
    app.catalogue_button = app.nav_buttons["catalogue"]
    app.deck = ttk.Frame(outer, width=1, height=1)
    app.deck.grid(row=0, column=1, sticky="nsew")
    app.deck.grid_propagate(False)
    app.deck.rowconfigure(0, weight=1)
    app.deck.columnconfigure(0, weight=1)
    app.run_panel = panel = ttk.Frame(app.deck, padding=22)
    ttk.Label(panel, text="钓鱼任务", style="Heading.TLabel").pack(anchor="w", pady=(0, 16))
    task = ttk.Frame(panel, style="Sheet.TFrame", padding=20)
    task.pack(fill="x", pady=(0, 16))
    ttk.Label(task, text="任务设置", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 12))
    controls = ttk.Frame(task, style="Card.TFrame")
    controls.pack(fill="x")
    ttk.Label(controls, text="任务模式").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=8)
    app.mode_box = ttk.Combobox(
        controls,
        textvariable=app.task_mode,
        values=["自由钓鱼", "按目标钓鱼"],
        state="readonly",
        width=22,
    )
    app.mode_box.grid(row=0, column=1, sticky="w")
    ttk.Label(controls, text="起始钓场").grid(row=1, column=0, sticky="w", pady=8)
    app.location_box = ttk.Combobox(
        controls, values=locations, textvariable=app.location, state="readonly", width=22
    )
    app.location_box.grid(row=1, column=1, sticky="w")
    app.clear_check = ttk.Checkbutton(task, text="满包时自动清理", variable=app.auto_clear)
    app.clear_check.pack(anchor="w", pady=(15, 6))
    app.awake_check = ttk.Checkbutton(task, text="运行时保持唤醒", variable=app.awake)
    app.awake_check.pack(anchor="w")
    progress = ttk.Frame(panel, style="Sheet.TFrame", padding=20)
    progress.pack(fill="x", pady=(0, 8))
    ttk.Label(progress, text="本次进度", style="CardTitle.TLabel").pack(anchor="w")
    app.target_summary = ttk.Label(progress, style="Hint.TLabel")
    app.target_summary.pack(fill="x", pady=16)
    app.parameter_summary = tk.StringVar()
    app.summary_label = ttk.Label(progress, textvariable=app.parameter_summary, style="Hint.TLabel")
    app.summary_label.pack(anchor="w")
    app.log_panel = ttk.Frame(panel, style="Card.TFrame")
    app.log_toggle = ttk.Button(panel, text="展开运行日志", command=app.toggle_logs)
    app.log_toggle.pack(anchor="w", pady=(18, 8))
    app.log_notice = tk.StringVar(value="保留 1500 条进展 · 完整内容见日志文件")
    build_logs(app, app.log_panel)
    app.catalogue = CataloguePage(app.deck, app)
    app.targets_page = TargetsPage(app.deck, app)
    app.catches_page = CatchesPage(app.deck, app)
    app.preferences = PreferencesPage(
        app.deck, app.services, preview=app.preview, on_saved=app._settings_saved
    )
    app.detail_log = app.preferences.detail_log
    app.trace_check = app.preferences.trace_check
    app.pages = {
        "run": app.run_panel,
        "catalogue": app.catalogue,
        "targets": app.targets_page,
        "catches": app.catches_page,
        "settings": app.preferences,
    }
    footer = ttk.Frame(root, padding=(22, 10), style="Card.TFrame")
    footer.grid(row=2, column=0, sticky="ew")
    footer.columnconfigure(0, weight=1)
    app.status_label = ttk.Label(
        footer, textvariable=app.status, foreground=ACCENT, font=(FONT, 12, "bold")
    )
    app.status_label.grid(row=0, column=0, sticky="w")
    app.detail_label = ttk.Label(
        footer, textvariable=app.detail, style="Hint.TLabel", wraplength=650
    )
    app.detail_label.grid(row=1, column=0, sticky="w", pady=(3, 0))
    app.action_button = ttk.Button(
        footer, text="▶ 开始钓鱼", style="Start.TButton", command=app.toggle_task
    )
    app.action_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(14, 0))
    app._settings_saved()
    app.show_page("run")
    center_window(root, app.services)


def build_logs(app, panel):
    toolbar = ttk.Frame(panel, style="Card.TFrame")
    toolbar.pack(fill="x", pady=(0, 8))
    ttk.Label(toolbar, text="运行记录", style="Section.TLabel").pack(side="left")
    ttk.Checkbutton(toolbar, text="自动滚动", variable=app.follow).pack(side="right")
    selector = ttk.Combobox(
        toolbar,
        textvariable=app.level,
        values=["运行信息", "警告 / 错误", "详细诊断"],
        state="readonly",
        width=12,
    )
    selector.pack(side="left", padx=14)
    selector.bind("<<ComboboxSelected>>", lambda _: app._render())
    text_frame = ttk.Frame(panel, style="Card.TFrame")
    text_frame.pack(fill="both", expand=True)
    app.text = tk.Text(
        text_frame,
        bg="#f5f8fa",
        fg="#344c57",
        relief="flat",
        wrap="word",
        font=(FONT, 9),
        padx=12,
        pady=10,
        state="disabled",
        height=1,
        width=1,
        selectbackground="#c8e6e1",
        highlightthickness=0,
        spacing1=2,
    )
    scroll = ttk.Scrollbar(text_frame, command=app.text.yview)
    app.text.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    app.text.pack(side="left", fill="both", expand=True)
    app.text.tag_configure("WARNING", foreground="#a2600e")
    app.text.tag_configure("ERROR", foreground="#b52f38")
    app.text.tag_configure("DEBUG", foreground="#677b91")
    app.issue_label = ttk.Label(panel, textvariable=app.issue, wraplength=550, style="Hint.TLabel")
    app.issue_label.pack(fill="x", pady=(8, 0))
    links = ttk.Frame(panel, style="Card.TFrame")
    links.pack(fill="x", pady=(10, 0))
    ttk.Button(links, text="日志目录", command=app.open_logs).pack(side="left")
    ttk.Button(links, text="异常截图", command=app.services.open_screenshot_directory).pack(
        side="left", padx=8
    )
    app.update_button = ttk.Button(links, text="更新与存储", command=lambda: app.updates.open())
    app.update_button.pack(side="right")
    panel.bind("<Configure>", app._resize_details)
