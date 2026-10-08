# -*- coding: utf-8 -*-
"""GUI 用到的通用控件。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable, Sequence

from . import mcstyle as mc

CHECKED = "☑"
UNCHECKED = "☐"

#: 状态配色（Treeview 的 tag）。真正的定义在 mcstyle 里，那边是照着
#: 「黑底彩字」的原版列表调的；这里保留这个名字只是为了别处的 import 不炸。
TAG_COLORS: dict[str, dict[str, str]] = mc.TAG_COLORS


class CheckTree(ttk.Frame):
    """带勾选列的 Treeview。

    Tk 的 Treeview 没有原生复选框，这里用第一列的 ``☑`` / ``☐`` 字形模拟。
    勾选列**没有标题**（原来写的是「选」，但那一列里画的本来就是方框，再顶一个
    「选」字既挤又多余）。

    两种用法：

    * ``link_selection=False``（默认，用于「整合包/实例」「其他设置」这类
      **清单**）：勾选状态是主体，存在 ``self._checked`` 里，点击方框列切换。
      这样即使某一行被筛选（``detach``）掉，它的勾选也不会丢。
    * ``link_selection=True``（用于「备份与还原」这类**选择列表**）：
      **勾选跟着选择走**——点一下打勾、Ctrl+点单个、Shift+点一段、Ctrl+A 全选、
      Esc 取消，方框实时反映选中的行。多选靠的就是 Treeview 自带的
      ``selectmode="extended"``。
    """

    def __init__(self, parent, columns: Sequence[tuple[str, str, int]],
                 on_toggle: Callable[[str, bool], None] | None = None,
                 height: int = 16, selectmode: str = "extended",
                 link_selection: bool = False) -> None:
        super().__init__(parent)
        self._on_toggle = on_toggle
        self._checked: dict[str, bool] = {}
        self._checkable = True
        self._link_selection = link_selection
        # set_checked / _on_select / selection_set 会互相触发，用一个重入标记挡住
        self._syncing = False

        self.column_ids = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=self.column_ids, show="headings",
                                 height=height, selectmode=selectmode)
        self.tree.heading(self.column_ids[0], text="")
        self.tree.column(self.column_ids[0], width=38, minwidth=34, anchor="center",
                         stretch=False)
        for index, (col_id, title, width) in enumerate(columns):
            if index == 0:
                continue
            self.tree.heading(col_id, text=title, command=lambda c=col_id: self._sort_by(c))
            self.tree.column(col_id, width=width, minwidth=48,
                             anchor="w" if width > 90 else "center", stretch=(width > 150))

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        # 选择驱动的树里，「全选/取消」就是最常用的两个操作，给上快捷键
        self.tree.bind("<Control-a>", self._on_select_all)
        self.tree.bind("<Control-A>", self._on_select_all)
        self.tree.bind("<Escape>", self._on_escape)
        self._sort_state: dict[str, bool] = {}

        for tag, options in TAG_COLORS.items():
            self.tree.tag_configure(tag, **options)

    # -- 勾选 ------------------------------------------------------------
    def set_checkable(self, checkable: bool) -> None:
        self._checkable = checkable

    def _on_click(self, event) -> None:
        # 选择驱动的树：点哪儿都是普通的 Treeview 点击，方框由选择推出来，
        # 所以这里什么都不做（否则单击会既切勾选又改选择，互相打架）。
        if not self._checkable or self._link_selection:
            return
        region = self.tree.identify_region(event.x, event.y)
        if region not in ("cell", "tree"):
            return
        column = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        if column not in ("#1", "#2") or region == "tree":
            # 第一列（或 show=tree 时的树列）视为勾选区
            if column != "#1":
                return
        self.toggle(iid)

    def _on_space(self, _event) -> None:
        if not self._checkable or self._link_selection:
            # 选择驱动的树交给 Treeview 自己处理空格（等于 Ctrl+点击）
            return
        for iid in self.tree.selection():
            self.toggle(iid)

    def _on_select_all(self, _event=None) -> str:
        if self._link_selection:
            self.tree.selection_set(self.tree.get_children())
        return "break"

    def _on_escape(self, _event=None) -> str:
        if self._link_selection:
            self.tree.selection_remove(*self.tree.selection())
        return "break"

    def _on_select(self, _event=None) -> None:
        """选择变化时把方框刷成「选中 = 打勾」。"""
        if not self._link_selection or self._syncing:
            return
        self._syncing = True
        try:
            selected = set(self.tree.selection())
            for iid in self.tree.get_children():
                want = iid in selected
                if self._checked.get(iid, False) != want:
                    self._checked[iid] = want
                    self._paint(iid)
        finally:
            self._syncing = False

    def _paint(self, iid: str) -> None:
        try:
            values = list(self.tree.item(iid, "values"))
        except tk.TclError:
            return          # 已经被删掉的行
        if not values:
            return
        values[0] = CHECKED if self._checked.get(iid, False) else UNCHECKED
        try:
            self.tree.item(iid, values=values)
        except tk.TclError:
            pass

    def _sync_selection(self) -> None:
        """把 Treeview 的选中项调成和勾选一致（只对可见行）。"""
        if not self._link_selection or self._syncing:
            return
        self._syncing = True
        try:
            wanted = [iid for iid in self.tree.get_children()
                      if self._checked.get(iid, False)]
            self.tree.selection_set(wanted)
        except tk.TclError:
            pass
        finally:
            self._syncing = False

    def toggle(self, iid: str) -> None:
        self.set_checked(iid, not self._checked.get(iid, False))
        if self._on_toggle is not None:
            self._on_toggle(iid, self._checked[iid])

    def set_checked(self, iid: str, checked: bool) -> None:
        self._checked[iid] = checked
        self._paint(iid)
        self._sync_selection()

    def is_checked(self, iid: str) -> bool:
        return self._checked.get(iid, False)

    def checked_items(self) -> list[str]:
        # 注意：这里不能用 tree.get_children()。筛选是靠 tree.detach() 做的，
        # 被筛掉的行会从 get_children() 里消失——那会让「一键同步」静默漏掉它们。
        return [iid for iid, on in self._checked.items() if on]

    def all_items(self) -> list[str]:
        """所有加过的行（含被筛掉、处于 detach 状态的行），按添加顺序。"""
        return list(self._checked)

    def set_all_checked(self, checked: bool) -> None:
        for iid in self.all_items():
            self._checked[iid] = checked
            self._paint(iid)
        self._sync_selection()

    # -- 行 --------------------------------------------------------------
    def clear(self) -> None:
        # detach 过的项不在 get_children() 里，只按它删会留下孤儿项，
        # 下次用同样的 iid 插入就会报 "Item <iid> already exists"。
        doomed = set(self.tree.get_children()) | set(self._checked)
        for iid in doomed:
            try:
                self.tree.delete(iid)
            except tk.TclError:
                pass
        self._checked.clear()

    def add_row(self, iid: str, values: Sequence, checked: bool = True,
                tags: Iterable[str] = ()) -> None:
        display = [CHECKED if checked else UNCHECKED] + list(values)
        self.tree.insert("", "end", iid=iid, values=display, tags=tuple(tags))
        self._checked[iid] = checked

    def update_row(self, iid: str, values: Sequence, tags: Iterable[str] | None = None) -> None:
        display = [CHECKED if self._checked.get(iid, False) else UNCHECKED] + list(values)
        if tags is not None:
            self.tree.item(iid, values=display, tags=tuple(tags))
        else:
            self.tree.item(iid, values=display)

    def row(self, iid: str) -> dict:
        """返回除勾选列以外的值，键为列 id。"""
        values = list(self.tree.item(iid, "values"))[1:]
        return dict(zip(self.column_ids[1:], values))

    def set_columns(self, columns: Sequence[tuple[str, str, int]]) -> None:
        """重建列（实例选择变化时用）。"""
        self.column_ids = [c[0] for c in columns]
        self.tree.configure(columns=self.column_ids)
        self.tree.heading(self.column_ids[0], text="")
        self.tree.column(self.column_ids[0], width=38, minwidth=34,
                         anchor="center", stretch=False)
        for index, (col_id, title, width) in enumerate(columns):
            if index == 0:
                continue
            self.tree.heading(col_id, text=title)
            self.tree.column(col_id, width=width, minwidth=48,
                             anchor="w" if width > 90 else "center",
                             stretch=(width > 150))

    # -- 排序 ------------------------------------------------------------
    def _sort_by(self, column: str) -> None:
        descending = self._sort_state.get(column, False)
        self._sort_state[column] = not descending
        index = self.column_ids.index(column)
        rows = [(self.tree.set(iid, column), iid) for iid in self.all_items()]

        def key_of(item):
            text = item[0]
            try:
                return (0, float(text))
            except (TypeError, ValueError):
                return (1, text.lower())

        rows.sort(key=key_of, reverse=descending)
        for position, (_, iid) in enumerate(rows):
            self.tree.move(iid, "", position)


class LogPane(ttk.Frame):
    """带滚动条的日志框（原版风格：黑底彩字）。"""

    def __init__(self, parent, height: int = 7) -> None:
        super().__init__(parent)
        self.text = tk.Text(self, height=height, wrap="word", state="disabled",
                            font=("Consolas", 9), relief="sunken", borderwidth=2,
                            background="#000000", foreground="#FFFFFF",
                            insertbackground="#FFFFFF", selectbackground="#3A4A8A",
                            selectforeground="#FFFFFF", highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=vsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.text.tag_configure("error", foreground="#FF5555")
        self.text.tag_configure("warn", foreground="#FFAA00")
        self.text.tag_configure("ok", foreground="#55FF55")
        self.text.tag_configure("dim", foreground="#AAAAAA")
        self._last: str | None = None

    def log(self, message: str, tag: str = "") -> None:
        # 连续重复的同一句话只留一条：一次扫描会触发好几轮刷新，
        # 否则日志区会被同一行「对比完成…」刷屏。
        if message == self._last:
            return
        self._last = message
        self.text.configure(state="normal")
        self.text.insert("end", message + "\n", tag)
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self) -> None:
        self._last = None
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


class ScrollFrame(ttk.Frame):
    """可滚动的容器（放设置项用）。"""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.inner = ttk.Frame(self.canvas)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        # 只在自己身上绑滚轮：以前用 bind_all + winfo_containing 判断，实际上
        # 滚轮滚到别的面板（日志、键位图）时这里也会跟着滚。
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)
        self.inner.bind("<Enter>", self._bind_wheel)
        self.inner.bind("<Leave>", self._unbind_wheel)

    def _on_inner(self, _event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _bind_wheel(self, _event=None) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _event=None) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event) -> None:
        try:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass
