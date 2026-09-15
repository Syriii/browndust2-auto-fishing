"""单个原生列表承载目标草稿，仅编辑时创建条件下拉框。"""

from tkinter import ttk

from bd2_fishing.app.fishing_collection import CONDITIONS


class TargetDraft(ttk.Treeview):
    def __init__(self, parent, service, changed):
        super().__init__(
            parent,
            columns=("condition",),
            show="tree headings",
            selectmode="browse",
            height=1,
            style="Draft.Treeview",
        )
        self.service, self.changed = service, changed
        self.heading("#0", text="鱼种", anchor="w")
        self.heading("condition", text="尺寸要求", anchor="w")
        self.column("#0", width=100, minwidth=60, stretch=True)
        self.column("condition", width=98, minwidth=80, stretch=False)
        self._values = {}
        self.editor = None
        self._editor_id = None
        self.bind("<ButtonRelease-1>", self._clicked)
        self.bind("<Return>", self._keyboard_edit)
        self.bind("<F2>", self._keyboard_edit)
        self.bind("<Escape>", lambda _: self._close_editor())
        self.bind("<Configure>", lambda _: self._close_editor())

    def sync(self, selected):
        if self._values == selected:
            return
        self._close_editor()
        for identity in self._values.keys() - selected.keys():
            self.delete(identity)
        for index, (identity, condition) in enumerate(selected.items()):
            if identity not in self._values:
                self.insert(
                    "",
                    index,
                    iid=identity,
                    text=self.service.by_id[identity].name,
                    values=(CONDITIONS[condition] + " ▾",),
                )
            elif self._values[identity] != condition:
                self.set(identity, "condition", CONDITIONS[condition] + " ▾")
        self._values = dict(selected)
        self.configure(height=max(1, len(selected)))

    def _clicked(self, event):
        identity = self.identify_row(event.y)
        if identity and self.identify_column(event.x) == "#1":
            self.edit(identity)

    def _keyboard_edit(self, event):
        if self.selection():
            self.edit(self.selection()[0])
        return "break"

    def edit(self, identity):
        self._close_editor()
        bounds = self.bbox(identity, "condition")
        if not bounds:
            return
        self.editor = editor = ttk.Combobox(
            self, values=list(CONDITIONS.values()), state="readonly", width=10
        )
        editor.set(CONDITIONS[self._values[identity]])
        x, y, width, height = bounds
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        editor.bind("<<ComboboxSelected>>", lambda _: self._commit(identity))
        editor.bind("<Escape>", lambda _: self._close_editor())
        editor.bind("<FocusOut>", self._defer_finish)

    def _defer_finish(self, event):
        if self._editor_id is None:
            self._editor_id = self.after_idle(self._finish_edit)

    def _commit(self, identity):
        condition = next(key for key, label in CONDITIONS.items() if label == self.editor.get())
        self._values[identity] = condition
        self.set(identity, "condition", CONDITIONS[condition] + " ▾")
        self.changed(identity, condition)
        self._close_editor()
        self.focus_set()

    def _finish_edit(self):
        self._editor_id = None
        if self.editor is not None and self.focus_get() is not self.editor:
            self._close_editor()

    def _close_editor(self):
        if self._editor_id is not None:
            self.after_cancel(self._editor_id)
            self._editor_id = None
        if self.editor is not None:
            editor, self.editor = self.editor, None
            editor.destroy()

    def destroy(self):
        self._close_editor()
        super().destroy()
