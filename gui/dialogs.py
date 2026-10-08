# -*- coding: utf-8 -*-
"""可复用的小对话框：选按键组合。

Minecraft 的键位本质上就是「一个键码 + 若干修饰键」，这里给一个可靠的列表选择器，
另外附带「直接按键」的快捷捕捉（能映射到 MC 键名的按键才会生效）。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from mcsync.keycodes import (
    MODIFIER_ORDER, UNBOUND, KeyCombo, all_named_codes, is_valid_key_code,
    key_display,
)

from . import mcstyle as mc

#: Tk 的 keysym -> Minecraft 键码。只收「一对一、不歧义」的那些。
_KEYSYM: dict[str, str] = {}


def _k(code: str) -> str:
    return f"key.keyboard.{code}"


for _c in "abcdefghijklmnopqrstuvwxyz":
    _KEYSYM[_c] = _k(_c)
    _KEYSYM[_c.upper()] = _k(_c)
for _d in "0123456789":
    _KEYSYM[_d] = _k(_d)
for _n in range(1, 25):
    _KEYSYM[f"F{_n}"] = _k(f"f{_n}")

_KEYSYM.update({
    "space": _k("space"),
    "Tab": _k("tab"),
    "ISO_Left_Tab": _k("tab"),
    "Return": _k("enter"),
    "KP_Enter": _k("keypad.enter"),
    "Escape": _k("escape"),
    "BackSpace": _k("backspace"),
    "Delete": _k("delete"),
    "Insert": _k("insert"),
    "Home": _k("home"),
    "End": _k("end"),
    "Prior": _k("page.up"),
    "Next": _k("page.down"),
    "Up": _k("up"),
    "Down": _k("down"),
    "Left": _k("left"),
    "Right": _k("right"),
    "Caps_Lock": _k("caps.lock"),
    "Num_Lock": _k("num.lock"),
    "Scroll_Lock": _k("scroll.lock"),
    "Print": _k("print.screen"),
    "Pause": _k("pause"),
    "Menu": _k("menu"),
    "minus": _k("minus"),
    "equal": _k("equal"),
    "bracketleft": _k("left.bracket"),
    "bracketright": _k("right.bracket"),
    "backslash": _k("backslash"),
    "semicolon": _k("semicolon"),
    "apostrophe": _k("apostrophe"),
    "grave": _k("grave.accent"),
    "comma": _k("comma"),
    "period": _k("period"),
    "slash": _k("slash"),
    "KP_0": _k("keypad.0"),
    "KP_1": _k("keypad.1"),
    "KP_2": _k("keypad.2"),
    "KP_3": _k("keypad.3"),
    "KP_4": _k("keypad.4"),
    "KP_5": _k("keypad.5"),
    "KP_6": _k("keypad.6"),
    "KP_7": _k("keypad.7"),
    "KP_8": _k("keypad.8"),
    "KP_9": _k("keypad.9"),
    "KP_Decimal": _k("keypad.decimal"),
    "KP_Divide": _k("keypad.divide"),
    "KP_Multiply": _k("keypad.multiply"),
    "KP_Subtract": _k("keypad.subtract"),
    "KP_Add": _k("keypad.add"),
    "KP_Equal": _k("keypad.equal"),
})

#: 单独按下这些键时只切换修饰键勾选框，不当作键码
_MODIFIER_KEYSYM: dict[str, str] = {
    "Shift_L": "SHIFT", "Shift_R": "SHIFT",
    "Control_L": "CONTROL", "Control_R": "CONTROL",
    "Alt_L": "ALT", "Alt_R": "ALT",
    "Meta_L": "WIN", "Meta_R": "WIN",
    "Super_L": "WIN", "Super_R": "WIN",
    "Win_L": "WIN", "Win_R": "WIN",
}


def keysym_to_code(keysym: str) -> str | None:
    """Tk keysym -> MC 键码；认不出来返回 ``None``。"""
    if not keysym:
        return None
    code = _KEYSYM.get(keysym)
    if code is None:
        code = _KEYSYM.get(keysym.lower() if len(keysym) == 1 else keysym)
    return code


def state_to_modifiers(state: int) -> tuple[str, ...]:
    """Tk 的 event.state 位掩码 -> MC 修饰键元组（按 MC 自己的顺序）。"""
    found: set[str] = set()
    if state & 0x0001:
        found.add("SHIFT")
    if state & 0x0004:
        found.add("CONTROL")
    if state & 0x0008 or state & 0x20000:   # X11 与 Windows 的 Mod1 位不同
        found.add("ALT")
    return tuple(m for m in MODIFIER_ORDER if m in found)


class KeyPickerDialog(tk.Toplevel):
    """选一个按键组合。接受后从 ``result`` 取 :class:`KeyCombo`。"""

    def __init__(self, master, *, title: str = "选择按键",
                 initial: KeyCombo | None = None, fonts: dict | None = None,
                 hint: str = "") -> None:
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.result: KeyCombo | None = None
        self._fonts = fonts or {}

        self._all = sorted(all_named_codes(), key=lambda c: (key_display(c).lower(), c))
        self._code = tk.StringVar(value=(initial.code if initial else UNBOUND))
        self._mods = {
            m: tk.BooleanVar(value=bool(initial and m in initial.modifiers))
            for m in MODIFIER_ORDER
        }

        self._build(hint)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<KeyPress>", self._on_key)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.resizable(True, True)

        self.update_idletasks()
        self.minsize(520, 460)
        _centre(self, master)
        self.grab_set()
        self.listbox.focus_set()

    # ------------------------------------------------------------------
    def _build(self, hint: str) -> None:
        pad = ttk.Frame(self, padding=10)
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, text="直接按键盘上的键即可捕捉；也可以在下面列表里挑。",
                  style="Title.TLabel").pack(anchor="w")
        if hint:
            ttk.Label(pad, text=hint, style="Hint.TLabel", wraplength=460,
                      justify="left").pack(anchor="w", pady=(2, 0))

        search = ttk.Frame(pad)
        search.pack(fill="x", pady=(8, 4))
        ttk.Label(search, text="搜索：").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refill())
        entry = ttk.Entry(search, textvariable=self.search_var)
        entry.pack(side="left", fill="x", expand=True)

        box = ttk.Frame(pad)
        box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(box, activestyle="none", exportselection=False,
                                  font=self._fonts.get("base"), height=14)
        vsb = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=vsb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._on_pick())
        self.listbox.bind("<Double-1>", lambda _e: self._accept())

        mods = ttk.Frame(pad)
        mods.pack(fill="x", pady=(8, 0))
        ttk.Label(mods, text="修饰键：").pack(side="left")
        mod_style = mc.check_style(ttk.Style(self), mc.ACCENT)
        for name, label in (("SHIFT", "Shift"), ("CONTROL", "Ctrl"),
                            ("ALT", "Alt"), ("WIN", "Win")):
            ttk.Checkbutton(mods, text=label, variable=self._mods[name], style=mod_style,
                            command=self._update_preview).pack(side="left", padx=(0, 8))

        self.preview = ttk.Label(pad, text="", style="Title.TLabel")
        self.preview.pack(anchor="w", pady=(8, 0))

        buttons = ttk.Frame(pad)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="未绑定", command=self._pick_unbound).pack(side="left")
        ttk.Button(buttons, text="取消", command=self._cancel).pack(side="right")
        ttk.Button(buttons, text="确定", style="Accent.TButton",
                   command=self._accept).pack(side="right", padx=(0, 6))

        self._refill(select=self._code.get())
        self._update_preview()

    def _visible_codes(self) -> list[str]:
        needle = (self.search_var.get() or "").strip().lower()
        if not needle:
            return self._all
        out = []
        for code in self._all:
            if needle in code.lower() or needle in key_display(code).lower():
                out.append(code)
        return out

    def _refill(self, select: str | None = None) -> None:
        codes = self._visible_codes()
        self.listbox.delete(0, "end")
        for code in codes:
            self.listbox.insert("end", f"{key_display(code):<12} {code}")
        target = select if select is not None else self._code.get()
        if target in codes:
            index = codes.index(target)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(index)
            self.listbox.see(index)

    def _selected_code(self) -> str | None:
        selection = self.listbox.curselection()
        if not selection:
            return None
        codes = self._visible_codes()
        index = int(selection[0])
        if 0 <= index < len(codes):
            return codes[index]
        return None

    def _on_pick(self) -> None:
        code = self._selected_code()
        if code:
            self._code.set(code)
            self._update_preview()

    def _pick_unbound(self) -> None:
        self._code.set(UNBOUND)
        for var in self._mods.values():
            var.set(False)
        self.search_var.set("")
        self._refill(select=UNBOUND)
        self._update_preview()

    def _on_key(self, event) -> None:
        keysym = event.keysym
        modifier = _MODIFIER_KEYSYM.get(keysym)
        if modifier:
            # 单独按修饰键 = 切换那个勾选框
            self._mods[modifier].set(not self._mods[modifier].get())
            self._update_preview()
            return "break"
        code = keysym_to_code(keysym)
        if code is None:
            return None
        self._code.set(code)
        pressed = state_to_modifiers(event.state)
        if pressed:
            for name, var in self._mods.items():
                var.set(name in pressed)
        self.search_var.set("")
        self._refill(select=code)
        self._update_preview()
        return "break"

    def _current(self) -> KeyCombo:
        return KeyCombo(code=self._code.get(),
                        modifiers=tuple(m for m in MODIFIER_ORDER if self._mods[m].get()))

    def _update_preview(self) -> None:
        combo = self._current()
        ok = is_valid_key_code(combo.code)
        self.preview.configure(
            text=f"当前：{combo.display()}   ({combo.to_options()})"
                 + ("" if ok else "   ⚠ 这个键码可能不被游戏接受"))

    def _accept(self) -> None:
        combo = self._current()
        if not is_valid_key_code(combo.code):
            from tkinter import messagebox
            if not messagebox.askyesno(
                    "键码可疑",
                    f"「{combo.code}」不是 MC 认识的键码，写进 options.txt 会被忽略。\n\n"
                    "仍然使用吗？", parent=self):
                return
        self.result = combo
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def _centre(window: tk.Toplevel, master) -> None:
    try:
        window.update_idletasks()
        px, py = master.winfo_rootx(), master.winfo_rooty()
        pw, ph = master.winfo_width(), master.winfo_height()
        w, h = window.winfo_width(), window.winfo_height()
        window.geometry(f"+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 3)}")
    except tk.TclError:
        pass


def ask_key(master, *, title: str = "选择按键", initial: KeyCombo | None = None,
            fonts: dict | None = None, hint: str = "") -> KeyCombo | None:
    """弹一个选键对话框，返回选中的组合或 ``None``。"""
    dialog = KeyPickerDialog(master, title=title, initial=initial, fonts=fonts, hint=hint)
    master.wait_window(dialog)
    return dialog.result


__all__ = ["KeyPickerDialog", "ask_key", "keysym_to_code", "state_to_modifiers",
           "mc"]
