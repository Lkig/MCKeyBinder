# -*- coding: utf-8 -*-
"""「键位图」标签页 —— 用键盘布局显示每个键被谁占用，并就地解绑/改键。

对应两只 Minecraft 模组的思路：
``[VK] 可视化键位图`` 用键盘布局展示绑定，``可视化按键绑定管理`` 在此之上加了
按模组/状态/关键词过滤和详情面板。本标签页把这两件事合在游戏外的同步工具里，
额外的好处是能直接对着「主配置」改键，改完一键同步到所有整合包。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from mcsync.keycodes import UNBOUND, KeyCombo, key_display
from mcsync.keymap_model import (
    STATE_CONFLICT, STATE_DIFF, STATE_FREE, STATE_NAMES, STATE_ORDER, STATE_SHORT,
    STATE_USED,
    build_key_usage, conflict_usages, groups_of, owners_of, state_counts,
)
from mcsync.profile import Profile

from . import mcstyle as mc
from .dialogs import ask_key
from .keymap import KeyState, KeymapCanvas, LAYOUTS
from .widgets import ScrollFrame


class KeymapTab(ttk.Frame):
    """键位图标签页。``host`` 是主窗口，需要提供 profile / diff_table /
    selected_instances() / save_profile() / refresh_diff() / log()。"""

    def __init__(self, parent, host) -> None:
        super().__init__(parent, padding=(10, 8, 10, 8))
        self.host = host
        self.usages: dict = {}
        self.selected_code: str = ""
        self.view_items: list[tuple[str, str | None]] = []
        self._sash_touched = False
        self._build()

    # ------------------------------------------------------------------
    # 搭界面
    # ------------------------------------------------------------------
    def _build(self) -> None:
        fonts = getattr(self.host, "fonts", {}) or {}

        bar = ttk.Frame(self)
        bar.pack(fill="x")

        ttk.Label(bar, text="布局：", style="Hint.TLabel").pack(side="left")
        self.layout_var = tk.StringVar(value=next(iter(LAYOUTS)))
        combo = ttk.Combobox(bar, textvariable=self.layout_var, state="readonly",
                             width=15, values=list(LAYOUTS))
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._on_layout())

        ttk.Label(bar, text="视角：", style="Hint.TLabel").pack(side="left", padx=(10, 0))
        self.view_var = tk.StringVar()
        self.view_combo = ttk.Combobox(bar, textvariable=self.view_var,
                                       state="readonly", width=17)
        self.view_combo.pack(side="left")
        self.view_combo.bind("<<ComboboxSelected>>", lambda _e: self._recompute())

        # 本页的保存/导入/同步放在第一行右侧，和顶栏的全局按钮区分开
        self._page_actions(bar)

        bar2 = ttk.Frame(self)
        bar2.pack(fill="x", pady=(6, 0))

        ttk.Label(bar2, text="关键词：", style="Hint.TLabel").pack(side="left")
        self.keyword_var = tk.StringVar()
        self.keyword_var.trace_add("write", lambda *_: self._recompute())
        ttk.Entry(bar2, textvariable=self.keyword_var, width=13).pack(side="left")

        ttk.Label(bar2, text="显示：", style="Hint.TLabel").pack(side="left", padx=(10, 0))
        self.state_vars: dict[str, tk.BooleanVar] = {}
        style = ttk.Style(self)
        for state in STATE_ORDER:
            var = tk.BooleanVar(value=True)
            self.state_vars[state] = var
            # 勾选框染成键位图里对应的状态色，一眼能对上图例。
            mark_style = mc.check_style(style, mc.KEY_STATE_STYLE[state][1])
            ttk.Checkbutton(bar2, text=STATE_SHORT[state], variable=var,
                            style=mark_style,
                            command=self._on_state_filter).pack(side="left", padx=(0, 6))

        quick = ttk.Frame(bar2)
        quick.pack(side="right")
        ttk.Button(quick, text="仅冲突", style="Small.TButton",
                   command=lambda: self._quick_states({STATE_CONFLICT})).pack(side="left")
        ttk.Button(quick, text="仅不同", style="Small.TButton",
                   command=lambda: self._quick_states({STATE_DIFF})).pack(
            side="left", padx=(4, 0))
        ttk.Button(quick, text="全部", style="Small.TButton",
                   command=lambda: self._quick_states(set(STATE_ORDER))).pack(
            side="left", padx=(4, 0))

        bar3 = ttk.Frame(self)
        bar3.pack(fill="x", pady=(4, 6))

        ttk.Label(bar3, text="分组：", style="Hint.TLabel").pack(side="left")
        self.group_var = tk.StringVar(value="全部")
        self.group_combo = ttk.Combobox(bar3, textvariable=self.group_var,
                                        state="readonly", width=14)
        self.group_combo.pack(side="left")
        self.group_combo.bind("<<ComboboxSelected>>", lambda _e: self._recompute())

        ttk.Label(bar3, text="归属：", style="Hint.TLabel").pack(side="left", padx=(10, 0))
        self.owner_var = tk.StringVar(value="全部")
        self.owner_combo = ttk.Combobox(bar3, textvariable=self.owner_var,
                                        state="readonly", width=14)
        self.owner_combo.pack(side="left")
        self.owner_combo.bind("<<ComboboxSelected>>", lambda _e: self._recompute())

        self.summary_var = tk.StringVar(value="")
        ttk.Label(bar3, textvariable=self.summary_var, style="Hint.TLabel").pack(
            side="right")

        # 键盘图和详情上下分栏，中间那条缝可以拖
        self.pane = ttk.PanedWindow(self, orient="vertical")
        self.pane.pack(fill="both", expand=True)

        self.canvas_frame = ttk.Frame(self.pane)
        self.keymap = KeymapCanvas(self.canvas_frame, on_select=self._on_select,
                                   fonts=fonts)
        self.keymap.pack(fill="both", expand=True)

        self.hint = ttk.Label(self.canvas_frame, text="", style="Hint.TLabel",
                              justify="center", wraplength=620, font=fonts.get("title"))
        self.pane.add(self.canvas_frame, weight=5)
        self.pane.bind("<ButtonRelease-1>", self._on_sash)
        # 窗口一变形 PanedWindow 会按 weight 重新分配，得再校一次缝的位置。
        self.pane.bind("<Configure>", lambda _e: self.after_idle(self.fit_sash))

        self._build_detail()

    def _page_actions(self, row: ttk.Frame) -> None:
        """本页的「保存方案 / 导入方案 / 同步」——样式比顶栏的全局按钮小一号。"""
        host = self.host
        hook = getattr(host, "_page_actions", None)
        if hook is not None:
            hook(row, host.on_sync_keybinds)
            return
        # 没有宿主支持（例如单独测试这个控件）就退化成只放同步按钮
        box = ttk.Frame(row)
        box.pack(side="right")
        ttk.Button(box, text="本页同步", style="SmallPrimary.TButton",
                   command=host.on_sync_keybinds).pack(side="left")

    def _build_detail(self) -> None:
        self.detail = ttk.Frame(self.pane, padding=(0, 8, 0, 0))

        head = ttk.Frame(self.detail)
        head.pack(fill="x")
        self.detail_title = ttk.Label(head, text="点击键盘上的任意键查看它绑定了什么",
                                      style="H2.TLabel")
        self.detail_title.pack(side="left")
        self.detail_state = ttk.Label(head, text="", style="Hint.TLabel")
        self.detail_state.pack(side="left", padx=(10, 0))

        self.detail_scroll = ScrollFrame(self.detail)
        self.detail_scroll.canvas.configure(height=150)
        self.detail_scroll.pack(fill="both", expand=True, pady=(4, 0))
        self.detail_body = self.detail_scroll.inner
        self.detail_body.columnconfigure(0, weight=1)

        self.detail_hint = ttk.Label(
            self.detail, style="Hint.TLabel", justify="left", wraplength=820,
            text="提示：绿色=已绑定，橙色=与主配置不同，红色=多个功能抢同一个键，"
                 "蓝色=当前选中。双击键位图上的键不能改键，请在下方详情里操作。")
        self.detail_hint.pack(fill="x", pady=(4, 0))

        self.pane.add(self.detail, weight=2)

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def _views(self) -> list[tuple[str, str | None]]:
        host = self.host
        profile = host.profile
        out: list[tuple[str, str | None]] = []
        label = f"主配置（{profile.name}）" if profile else "主配置"
        out.append((label, None))
        for instance in host.selected_instances():
            out.append((instance.name, instance.key))
        return out

    def _current_view_key(self) -> str | None:
        label = self.view_var.get()
        for name, key in self._views():
            if name == label:
                return key
        return None

    def refresh(self) -> None:
        """对比表变了以后重建整个标签页。"""
        host = self.host
        table = host.diff_table

        views = self._views()
        self.view_items = views
        labels = [name for name, _ in views]
        self.view_combo["values"] = labels
        if self.view_var.get() not in labels:
            self.view_var.set(labels[0])

        if table is None:
            self.group_combo["values"] = ["全部"]
            self.owner_combo["values"] = ["全部"]
            self.group_var.set("全部")
            self.owner_var.set("全部")
            self.usages = {}
            self.keymap.set_states({})
            self.summary_var.set("")
            self._set_hint("先选一份主配置并勾选要同步的整合包，键盘图就会点亮。")
            self._update_detail()
            return

        groups = ["全部"] + groups_of(table)
        owners = ["全部"] + owners_of(table)
        for combo, var, values in ((self.group_combo, self.group_var, groups),
                                   (self.owner_combo, self.owner_var, owners)):
            old = var.get()
            combo["values"] = values
            var.set(old if old in values else "全部")

        self._set_hint("")
        self._recompute()

    def fit_sash(self) -> None:
        """把上下分栏的缝放到「键盘图正好看全」的位置。

        只在用户没手动拖过的时候动它，免得把人家调好的比例冲掉。
        """
        if getattr(self, "_sash_touched", False):
            return
        try:
            self.update_idletasks()
            total = self.pane.winfo_height()
            need = self.keymap.preferred_height() + 6
            current = self.pane.sashpos(0)
        except tk.TclError:
            return
        if total < 220:
            return
        pos = max(160, min(need, total - 116))
        # 差 2 像素以内就别动了，否则 set → <Configure> → set 会转圈。
        if abs(pos - current) <= 2:
            return
        try:
            self.pane.sashpos(0, pos)
        except tk.TclError:
            pass

    def _on_sash(self, event=None) -> None:
        """只有真的按在缝上才算「用户手动调过」。

        直接无条件标记的话，点一下详情区的「改键…」就会关掉自动适配。
        """
        if event is None:
            self._sash_touched = True
            return
        try:
            pos = self.pane.sashpos(0)
        except tk.TclError:
            return
        if abs(getattr(event, "y", 10 ** 6) - pos) <= 6:
            self._sash_touched = True

    def _recompute(self) -> None:
        table = self.host.diff_table
        if table is None:
            return
        group = self.group_var.get()
        owner = self.owner_var.get()
        self.usages = build_key_usage(
            table,
            self._current_view_key(),
            targets=[i.key for i in self.host.selected_instances()],
            keyword=self.keyword_var.get(),
            group=None if group in ("", "全部") else group,
            owner=None if owner in ("", "全部") else owner,
        )
        self._apply_states()

    def _on_layout(self) -> None:
        self.keymap.set_layout(self.layout_var.get())

    def _on_state_filter(self) -> None:
        self._apply_states()

    def _quick_states(self, states: set[str]) -> None:
        for state, var in self.state_vars.items():
            var.set(state in states)
        self._apply_states()

    def _apply_states(self) -> None:
        allowed = {s for s, var in self.state_vars.items() if var.get()}
        states: dict[str, KeyState] = {}
        for code, usage in self.usages.items():
            if usage.state not in allowed:
                continue
            states[code] = KeyState(state=usage.state, count=usage.count,
                                    details=usage.summary_lines())
        self.keymap.set_states(states)
        self.keymap.set_selected(self.selected_code)

        counts = state_counts(self.usages)
        conflicts = len(conflict_usages(self.usages))
        self.summary_var.set(
            f"占用 {len(self.usages)} 个键 ｜ 已绑定 {counts[STATE_USED]} ｜ "
            f"与主配置不同 {counts[STATE_DIFF]} ｜ 冲突 {conflicts}")
        self.after_idle(self.fit_sash)
        self._update_detail()

    def _set_hint(self, text: str) -> None:
        self.hint.configure(text=text)
        if text:
            self.hint.place(relx=0.5, rely=0.06, anchor="n")
        else:
            self.hint.place_forget()

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------
    def _on_select(self, code: str) -> None:
        self.selected_code = code
        self._update_detail()

    def _update_detail(self) -> None:
        for child in self.detail_body.winfo_children():
            child.destroy()

        code = self.selected_code
        usage = self.usages.get(code) if code else None
        if code and usage is not None:
            self.detail_title.configure(text=f"{key_display(code)}   {code}")
            self.detail_state.configure(
                text=f"状态：{STATE_NAMES.get(usage.state, usage.state)}"
                     f"（{usage.count} 个功能）")
        elif code:
            self.detail_title.configure(text=f"{key_display(code)}   {code}")
            self.detail_state.configure(text="状态：空闲（没有功能使用这个键）")
        else:
            self.detail_title.configure(text="点击键盘上的任意键查看它绑定了什么")
            self.detail_state.configure(text="")

        if not code:
            ttk.Label(self.detail_body, style="Hint.TLabel",
                      text="也可以先点上面的「仅冲突」看看有没有键位打架。").grid(
                row=0, column=0, sticky="w", pady=4)
            return

        if usage is None or not usage.bindings:
            ttk.Label(self.detail_body, style="Hint.TLabel",
                      text="这个键在当前视角下没有绑定任何功能。").grid(
                row=0, column=0, sticky="w", pady=4)
            return

        editable = self._current_view_key() is None and self.host.profile is not None
        header = ["功能", "分类", "归属", "当前键"]
        if editable:
            header.append("操作")
        for col, text in enumerate(header):
            ttk.Label(self.detail_body, text=text, style="Hint.TLabel").grid(
                row=0, column=col, sticky="w", padx=(0, 12))

        for index, ref in enumerate(usage.bindings, start=1):
            ttk.Label(self.detail_body, text=ref.display).grid(
                row=index, column=0, sticky="w", padx=(0, 12))
            ttk.Label(self.detail_body, text=ref.group, style="Hint.TLabel").grid(
                row=index, column=1, sticky="w", padx=(0, 12))
            ttk.Label(self.detail_body, text=ref.owner_name, style="Hint.TLabel").grid(
                row=index, column=2, sticky="w", padx=(0, 12))
            text = ref.value.display() if ref.value else "-"
            if ref.differs:
                text += "  ⚠"
            ttk.Label(self.detail_body, text=text).grid(
                row=index, column=3, sticky="w", padx=(0, 12))
            if editable:
                buttons = ttk.Frame(self.detail_body)
                buttons.grid(row=index, column=4, sticky="w")
                ttk.Button(buttons, text="改键…", width=8,
                           command=lambda r=ref: self._rebind(r)).pack(side="left")
                ttk.Button(buttons, text="解绑", width=6,
                           command=lambda r=ref: self._unbind(r)).pack(side="left", padx=(4, 0))

        if not editable:
            ttk.Label(self.detail_body, style="Hint.TLabel",
                      wraplength=760, justify="left",
                      text="实例视角是只读的。要改键请切回「主配置」视角改，"
                           "再回上一页一键同步。").grid(
                row=len(usage.bindings) + 1, column=0, columnspan=5,
                sticky="w", pady=(6, 0))

    # ------------------------------------------------------------------
    # 就地改主配置
    # ------------------------------------------------------------------
    def _commit_edit(self, binding_name: str, combo: KeyCombo, what: str) -> None:
        profile: Profile = self.host.profile
        profile.set(binding_name, combo)
        self.host.save_profile(profile)
        self.host.log(f"主配置「{profile.name}」：{what} -> {combo.display()}", "ok")
        self.selected_code = combo.code if combo.code != UNBOUND else ""
        self.host.refresh_diff()

    def _rebind(self, ref) -> None:
        combo = ask_key(
            self, title=f"给「{ref.display}」绑定按键", initial=ref.value,
            fonts=getattr(self.host, "fonts", {}) or {},
            hint=f"功能：{ref.display}（{ref.group} / {ref.owner_name}）")
        if combo is None or combo == ref.value:
            return
        self._commit_edit(ref.binding_name, combo, ref.display)

    def _unbind(self, ref) -> None:
        if not messagebox.askyesno(
                "解绑", f"把主配置里的「{ref.display}」设为未绑定？\n\n"
                        "之后同步到整合包时，这个功能会被解绑（除非在『同步选项』里"
                        "关掉了相应行为）。", parent=self):
            return
        self._commit_edit(ref.binding_name, KeyCombo(code=UNBOUND), ref.display)


__all__ = ["KeymapTab"]
