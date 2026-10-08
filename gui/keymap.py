# -*- coding: utf-8 -*-
"""可视化键位图：把键盘/鼠标画出来，按按键状态着色。

对标两个参考 Mod 的做法（[VK] Visual Keymap 的键盘布局可视化、
New Visual Keybing 的「空闲 / 冲突 / 所属模组」状态着色）：

* 每个物理按键是一个格子，格子的**颜色**代表这个键的状态；
* 点一个键 → 上抛 ``on_select(code)``，由主窗口把详情显示在旁边的面板里；
* 悬停 → 显示这个键上绑了哪些功能。

布局用「字符单位（u）」描述，1u 就是一个标准键宽。这样加布局只是加一张
数据表，不用碰绘制代码。实际像素尺寸在 ``<Configure>`` 时按控件宽度反算，
所以窗口拉宽拉窄键盘都会自动铺满、不会被裁掉。
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from . import mcstyle as mc


@dataclass(frozen=True)
class KeySpec:
    """一个物理按键的几何信息（单位是 u，不是像素）。"""

    code: str
    label: str
    x: float
    y: float
    w: float = 1.0
    h: float = 1.0


_K = "key.keyboard."

# 键位图里与 unit 无关的固定高度：鼠标区标题 26px + 图例间距 22px + 上下内边距。
_FIXED_H = 72.0

#: 画布高度低于这两个值时，先省掉鼠标区和图例（键帽太小的键盘没法看）
_MOUSE_MIN_H = 250.0
_LEGEND_MIN_H = 205.0
_MOUSE_H = 38.0      # 「鼠标」标题 + 行距
_LEGEND_H = 22.0     # 图例行距
_PAD_PX = 12.0       # 上下内边距

_M = "key.mouse."

#: 只影响「怎么画」不影响「是什么」：``-`` 和 ``=` 这几个 ASCII 符号在 8pt 下
#: 只有两三个像素，画在键帽正中几乎看不见，用户会以为这个键没被识别到。
#: 换成全角等价符号（同样是键盘上印的那两个字符的意思）就醒目多了。
_LABEL_ALIASES = {
    "-": "－",   # 减号
    "=": "＝",   # 等号
    "`": "～",   # 波浪号
    "\\": "＼",  # 反斜杠
}


def _draw_label(label: str) -> str:
    """把太细的符号换成画得清楚的等价写法（详情面板里仍是原始键值）。"""
    return _LABEL_ALIASES.get(label, label)


def _row(y: float, items: Sequence[tuple[str | None, str, float]],
         x0: float = 0.0) -> list[KeySpec]:
    """按顺序把一行按键摆开；``code is None`` 表示留一段空隙。"""
    out: list[KeySpec] = []
    x = x0
    for code, label, width in items:
        if code is not None:
            out.append(KeySpec(code, label, x, y, width))
        x += width
    return out


def _fkeys(start: float) -> list[tuple[str | None, str, float]]:
    items: list[tuple[str | None, str, float]] = []
    for i in range(4):
        items.append((f"{_K}f{start + i}", f"F{start + i}", 1.0))
    return items


def _build_full() -> tuple[list[KeySpec], float, float]:
    """标准 104 键 ANSI 布局。

    主键区宽 15u，右边隔 0.5u 是 3u 宽的方向/编辑键区，再隔 0.5u 是 4u 宽的小键盘。
    总宽 23u，共 6 行。
    """
    keys: list[KeySpec] = []

    # 第 0 行：Esc + F1–F12 + 打印屏幕/滚动锁定/暂停
    keys += _row(0, [(_K + "escape", "Esc", 1.0), (None, "", 1.0)]
                 + _fkeys(1) + [(None, "", 0.5)] + _fkeys(5)
                 + [(None, "", 0.5)] + _fkeys(9)
                 + [(None, "", 0.5),
                    (_K + "print.screen", "PrtSc", 1.0),
                    (_K + "scroll.lock", "ScrLk", 1.0),
                    (_K + "pause", "Pause", 1.0)])

    # 第 1 行：数字行 + 退格；右侧是编辑键区第一排 + 小键盘第一排
    number_row: list[tuple[str | None, str, float]] = [(_K + "grave.accent", "~", 1.0)]
    for i in range(1, 10):
        number_row.append((f"{_K}{i}", str(i), 1.0))
    number_row += [(_K + "0", "0", 1.0), (_K + "minus", "-", 1.0),
                   (_K + "equal", "=", 1.0), (_K + "backspace", "退格", 2.0),
                   (None, "", 0.5),
                   (_K + "insert", "Ins", 1.0), (_K + "home", "Home", 1.0),
                   (_K + "page.up", "PgUp", 1.0),
                   (None, "", 0.5),
                   (_K + "num.lock", "NumLk", 1.0),
                   (_K + "keypad.divide", "KP/", 1.0),
                   (_K + "keypad.multiply", "KP*", 1.0),
                   (_K + "keypad.subtract", "KP-", 1.0)]
    keys += _row(1, number_row)

    # 第 2 行：Tab + QWERTY + 回车左侧；编辑键区第二排 + 小键盘第二排
    letters = "QWERTYUIOP"
    row2: list[tuple[str | None, str, float]] = [(_K + "tab", "Tab", 1.5)]
    row2 += [(f"{_K}{c.lower()}", c, 1.0) for c in letters]
    row2 += [(_K + "left.bracket", "[", 1.0), (_K + "right.bracket", "]", 1.0),
             (_K + "backslash", "\\", 1.5),
             (None, "", 0.5),
             (_K + "delete", "Del", 1.0), (_K + "end", "End", 1.0),
             (_K + "page.down", "PgDn", 1.0),
             (None, "", 0.5),
             (_K + "keypad.7", "KP7", 1.0), (_K + "keypad.8", "KP8", 1.0),
             (_K + "keypad.9", "KP9", 1.0)]
    keys += _row(2, row2)
    # 小键盘加号是双高键
    keys.append(KeySpec(_K + "keypad.add", "KP+", 22.0, 2.0, 1.0, 2.0))

    # 第 3 行：Caps + ASDF + 分号引号 + 回车；小键盘第三排
    letters = "ASDFGHJKL"
    row3: list[tuple[str | None, str, float]] = [(_K + "caps.lock", "Caps", 1.75)]
    row3 += [(f"{_K}{c.lower()}", c, 1.0) for c in letters]
    row3 += [(_K + "semicolon", ";", 1.0), (_K + "apostrophe", "'", 1.0),
             (_K + "enter", "回车", 2.25),
             (None, "", 0.5),
             (None, "", 3.0),
             (None, "", 0.5),
             (_K + "keypad.4", "KP4", 1.0), (_K + "keypad.5", "KP5", 1.0),
             (_K + "keypad.6", "KP6", 1.0)]
    keys += _row(3, row3)

    # 第 4 行：左Shift + ZXCV + 右Shift + 方向键上；小键盘第四排
    letters = "ZXCVBNM"
    row4: list[tuple[str | None, str, float]] = [(_K + "left.shift", "Shift", 2.25)]
    row4 += [(f"{_K}{c.lower()}", c, 1.0) for c in letters]
    row4 += [(_K + "comma", ",", 1.0), (_K + "period", ".", 1.0),
             (_K + "slash", "/", 1.0), (_K + "right.shift", "Shift", 2.75),
             (None, "", 0.5), (None, "", 1.0),
             (_K + "up", "↑", 1.0), (None, "", 1.0),
             (None, "", 0.5),
             (_K + "keypad.1", "KP1", 1.0), (_K + "keypad.2", "KP2", 1.0),
             (_K + "keypad.3", "KP3", 1.0)]
    keys += _row(4, row4)
    keys.append(KeySpec(_K + "keypad.enter", "KP↵", 22.0, 4.0, 1.0, 2.0))

    # 第 5 行：修饰键 + 空格 + 方向键；小键盘最后一行
    row5: list[tuple[str | None, str, float]] = [
        (_K + "left.control", "Ctrl", 1.25), (_K + "left.win", "Win", 1.25),
        (_K + "left.alt", "Alt", 1.25), (_K + "space", "", 6.25),
        (_K + "right.alt", "Alt", 1.25), (_K + "right.win", "Win", 1.25),
        (_K + "menu", "Menu", 1.25), (_K + "right.control", "Ctrl", 1.25),
        (None, "", 0.5),
        (_K + "left", "←", 1.0), (_K + "down", "↓", 1.0), (_K + "right", "→", 1.0),
        (None, "", 0.5),
        (_K + "keypad.0", "KP0", 2.0), (_K + "keypad.decimal", "KP.", 1.0),
    ]
    keys += _row(5, row5)
    return keys, 23.0, 6.0


FULL_KEYS, FULL_W, FULL_H = _build_full()
#: 87 键（无小键盘）：直接按横坐标裁掉右半边
TKL_KEYS = [k for k in FULL_KEYS if k.x + k.w <= 18.6]

MOUSE_KEYS: list[KeySpec] = [
    KeySpec(_M + "left", "左键", 0.0, 0.0, 1.6),
    KeySpec(_M + "right", "右键", 1.7, 0.0, 1.6),
    KeySpec(_M + "middle", "中键", 3.4, 0.0, 1.6),
    KeySpec(_M + "4", "侧键 4", 5.1, 0.0, 1.6),
    KeySpec(_M + "5", "侧键 5", 6.8, 0.0, 1.6),
    KeySpec(_M + "6", "侧键 6", 8.5, 0.0, 1.6),
    KeySpec(_M + "7", "侧键 7", 10.2, 0.0, 1.6),
    KeySpec(_M + "8", "侧键 8", 11.9, 0.0, 1.6),
]
MOUSE_W = 13.5

LAYOUTS: dict[str, tuple[list[KeySpec], float, float]] = {
    "完整键盘（104 键）": (FULL_KEYS, FULL_W, FULL_H),
    "紧凑键盘（87 键，无小键盘）": (TKL_KEYS, 18.5, FULL_H),
}


@dataclass
class KeyState:
    """一个键在当前主配置 / 目标实例下的汇总状态。"""

    state: str = "free"                 # free / used / conflict / diff / selected
    count: int = 0                      # 绑在这个键上的功能数
    details: list[str] = field(default_factory=list)   # 每行一条，用于悬停/详情

    @property
    def style_name(self) -> str:
        return mc.KEY_STATE_STYLE.get(self.state, mc.KEY_STATE_STYLE["used"])[0]


class KeymapCanvas(tk.Frame):
    """可点击的键盘热力图。"""

    def __init__(self, parent, on_select: Callable[[str], None] | None = None,
                 fonts: dict | None = None) -> None:
        super().__init__(parent)
        self.on_select = on_select
        self.fonts = fonts or {"base": ("Microsoft YaHei UI", 9), "small": ("Microsoft YaHei UI", 8)}

        self.canvas = tk.Canvas(self, background=mc.CANVAS_BG, highlightthickness=0,
                                borderwidth=0)
        vsb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        hsb = tk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._layout = next(iter(LAYOUTS))
        self._states: dict[str, KeyState] = {}
        self._selected: str | None = None
        self._hover: str | None = None
        self._specs: dict[str, KeySpec] = {}
        self._unit = 40.0
        self._content_height = 0.0
        self._origin = (0.0, 0.0)
        self._tooltip = mc.Tooltip(self.canvas, delay=250)
        self._last_size = (0, 0)

        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        self.canvas.bind("<Configure>", self._on_configure)

    # -- 对外接口 --------------------------------------------------------
    def set_layout(self, name: str) -> None:
        if name in LAYOUTS and name != self._layout:
            self._layout = name
            self.refresh()

    def set_states(self, states: dict[str, KeyState]) -> None:
        self._states = dict(states)
        self.refresh()

    def set_selected(self, code: str | None) -> None:
        if code == self._selected:
            return
        self._selected = code
        self.refresh()

    @property
    def layout_name(self) -> str:
        return self._layout

    @property
    def states(self) -> dict[str, KeyState]:
        """当前着色用到的状态（只读副本，方便测试断言）。"""
        return dict(self._states)

    @property
    def selected(self) -> str | None:
        return self._selected

    # -- 绘制 ------------------------------------------------------------
    def _on_configure(self, event) -> None:
        if (event.width, event.height) == self._last_size:
            return
        self._last_size = (event.width, event.height)
        self.refresh()

    def _unit_for(self, width: int) -> float:
        keys, total_w, _ = LAYOUTS[self._layout]
        # 左右各留一点边距；行标签区额外留 1.4u
        usable = max(width - 40, 320)
        unit = usable / (total_w + 0.6)
        return max(24.0, min(52.0, unit))

    def refresh(self) -> None:
        c = self.canvas
        # 悬停/选中都会整幅重画，重画前先记住滚动位置，否则鼠标一动视图就跳回原点
        try:
            view_y = c.yview()[0]
            view_x = c.xview()[0]
        except tk.TclError:
            view_y = view_x = 0.0
        c.delete("all")
        keys, total_w, total_h = LAYOUTS[self._layout]
        width = max(self.canvas.winfo_width(), 640)
        unit = self._unit_for(width)

        # 高度不够时先砍装饰（鼠标区、图例），再缩键帽——用户最想看的是键盘本体。
        height = self.canvas.winfo_height()
        show_mouse = height <= 0 or height >= _MOUSE_MIN_H
        show_legend = height <= 0 or height >= _LEGEND_MIN_H
        extra_u = (1 if show_mouse else 0) + (1 if show_legend else 0)
        extra_px = _PAD_PX
        if show_mouse:
            extra_px += _MOUSE_H
        if show_legend:
            extra_px += _LEGEND_H
        if height > 120:
            unit = min(unit, max(16.0, (height - extra_px) / (total_h + extra_u)))
        self._unit = unit
        gap = max(2.0, unit * 0.08)
        pad_x = 16.0
        pad_y = 12.0

        self._specs = {spec.code: spec for spec in keys}

        for spec in keys:
            self._draw_key(spec, unit, gap, pad_x, pad_y)

        bottom = pad_y + total_h * unit

        # ---- 鼠标区 ----
        if show_mouse:
            mouse_y = bottom + 26
            mc.mc_text(c, pad_x, mouse_y - 12, "鼠标", fill=mc.CANVAS_DIM,
                       font=self.fonts["small"], anchor="w", shadow="")
            for spec in MOUSE_KEYS:
                x0 = pad_x + spec.x * unit
                self._draw_box(spec.code, spec.label, x0, mouse_y,
                               spec.w * unit - gap, unit - gap)
            bottom = mouse_y + unit

        # ---- 图例 ----
        if show_legend:
            legend_y = bottom + 22
            lx = pad_x
            for state in ("free", "used", "diff", "conflict", "selected"):
                label, face, light, dark, fg = mc.KEY_STATE_STYLE[state]
                mc.bevel(c, lx, legend_y, lx + unit * 0.72, legend_y + unit * 0.72,
                         face=face, light=light, dark=dark, b=2)
                text = c.create_text(lx + unit * 0.86, legend_y + unit * 0.36, text=label,
                                     fill=mc.CANVAS_FG, font=self.fonts["small"], anchor="w")
                lx += unit * 0.86 + c.bbox(text)[2] - c.bbox(text)[0] + unit * 0.45

            if any(st.count >= 2 for st in self._states.values()):
                c.create_text(lx, legend_y + unit * 0.36,
                              text="键角上的数字 = 抢这个键的功能个数（≥2 才画）",
                              fill=mc.GRAY, font=self.fonts["small"], anchor="w")
            bottom = legend_y + unit

        total_height = bottom + pad_y
        # 宽度富裕时（标签页现在占满整幅窗口）把键盘居中，别挤在左边
        content_w = total_w * unit + 2 * pad_x
        offset_x = max(0.0, (width - content_w) / 2.0)
        if offset_x:
            c.move("all", offset_x, 0)
        self._content_height = total_height
        c.configure(scrollregion=(0, 0, max(width, content_w), total_height))
        if view_y or view_x:
            c.yview_moveto(view_y)
            c.xview_moveto(view_x)

    def preferred_height(self) -> int:
        """整幅键位图在「宽度铺满」时需要的像素高度。

        标签页用它给上下分栏设一个「一眼看全」的初始位置。这里**只按宽度算**，
        不参考当前画布高度——否则画布高度→unit→preferred→分栏高度会自己转圈。
        """
        _, _, total_h = LAYOUTS[self._layout]
        unit = self._unit_for(max(self.canvas.winfo_width(), 640))
        # 6 行主键区 + 1 行鼠标 + 1 行图例
        return int((total_h + 2) * unit + _FIXED_H)

    def _draw_key(self, spec: KeySpec, unit: float, gap: float,
                  pad_x: float, pad_y: float) -> None:
        x0 = pad_x + spec.x * unit
        y0 = pad_y + spec.y * unit
        self._draw_box(spec.code, spec.label, x0, y0,
                       spec.w * unit - gap, spec.h * unit - gap)

    def _draw_box(self, code: str, label: str, x0: float, y0: float,
                  w: float, h: float) -> None:
        state = self._states.get(code)
        style = state.state if state else "free"
        if code == self._selected:
            style = "selected"
        elif code == self._hover and style == "free":
            style = "used"
        _, face, light, dark, fg = mc.KEY_STATE_STYLE[style]

        tag = f"key::{code}"
        mc.bevel(self.canvas, x0, y0, x0 + w, y0 + h,
                 face=face, light=light, dark=dark, b=2, tags=(tag,))
        font = self.fonts["small"] if w < 34 else self.fonts["base"]
        if label:
            mc.mc_text(self.canvas, x0 + w / 2, y0 + h / 2, _draw_label(label), fill=fg,
                       font=font, shadow="#2A2A2A", tags=(tag,))
        if state and state.count >= 2:
            # 右上角标出「几个功能挤在这个键上」；只绑一个功能的键靠底色已经能表达，
            # 再画一个「1」角标只会让整块键盘变吵。
            self.canvas.create_oval(x0 + w - 15, y0 + 3, x0 + w - 3, y0 + 15,
                                    fill=mc.BLACK, outline=mc.BLACK, tags=(tag,))
            mc.mc_text(self.canvas, x0 + w - 9, y0 + 9,
                       str(state.count) if state.count < 10 else "9+",
                       fill=mc.ACCENT, font=self.fonts["small"], shadow="",
                       tags=(tag,))

    # -- 交互 ------------------------------------------------------------
    def _code_at(self, event) -> str | None:
        item = self.canvas.find_withtag("current")
        if not item:
            return None
        for tag in self.canvas.gettags(item[0]):
            if tag.startswith("key::"):
                return tag[5:]
        return None

    def _set_hover(self, code: str | None) -> None:
        if code == self._hover:
            return
        self._hover = code
        self.refresh()
        if code:
            unit = self._unit
            x = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
            y = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
            self._tooltip.schedule(self.tooltip_text(code), x, y)
        else:
            self._tooltip.cancel()

    def _on_motion(self, event) -> None:
        self._set_hover(self._code_at(event))

    def _on_click(self, event) -> None:
        code = self._code_at(event)
        if code is None:
            return
        self._tooltip.cancel()
        self.set_selected(None if code == self._selected else code)
        if self.on_select is not None:
            self.on_select(self._selected or "")

    def tooltip_text(self, code: str) -> str:
        from mcsync.keycodes import key_display

        head = f"{key_display(code)}  ({code})"
        state = self._states.get(code)
        if state is None or not state.details:
            return f"{head}\n—— 空闲，没有功能绑在这个键上"
        return head + "\n" + "\n".join(state.details[:12])
