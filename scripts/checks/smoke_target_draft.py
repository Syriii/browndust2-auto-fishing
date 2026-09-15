"""真实 Tcl 下拉菜单的焦点与提交回归；不连接游戏、不访问用户数据。"""

import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

from bd2_fishing.ui.target_draft import TargetDraft
from bd2_fishing.ui.theme import apply_theme


def main():
    root = tk.Tk()
    root.title("目标尺寸菜单验证")
    apply_theme(root)
    errors, changes = [], []
    root.report_callback_exception = lambda *error: errors.append(error)
    service = SimpleNamespace(by_id={"fish": SimpleNamespace(name="测试鱼")})
    draft = TargetDraft(root, service, lambda *value: changes.append(value))
    draft.pack(fill="both", expand=True)
    outside = ttk.Entry(root)
    outside.pack()
    draft.sync({"fish": "any"})

    def pump():
        for _ in range(5):
            root.update()
            time.sleep(0.02)
        assert not errors, errors

    try:
        pump()
        draft.edit("fish")
        editor = draft.editor
        root.tk.call("focus", "-force", str(editor))
        pump()
        root.tk.call("ttk::combobox::Post", str(editor))
        popup = str(root.tk.call("ttk::combobox::PopdownWindow", str(editor)))
        listbox = popup + ".f.l"
        root.tk.call("focus", "-force", listbox)
        pump()
        assert draft.editor is editor
        assert root.tk.call("winfo", "ismapped", popup)
        root.tk.call(listbox, "selection", "clear", 0, "end")
        root.tk.call(listbox, "selection", "set", 3)
        root.tk.call(listbox, "activate", 3)
        root.tk.call("event", "generate", listbox, "<Return>")
        pump()
        assert changes == [("fish", "both")], changes
        assert draft.editor is None
        draft.edit("fish")
        root.tk.call("focus", "-force", str(draft.editor))
        pump()
        draft.editor.event_generate("<Escape>")
        pump()
        assert draft.editor is None
        draft.edit("fish")
        root.tk.call("focus", "-force", str(draft.editor))
        pump()
        outside.focus_force()
        pump()
        assert draft.editor is None
        assert changes == [("fish", "both")]
        print("PASS: Tcl popup focus, keyboard commit, Escape and outside-focus dismissal")
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
