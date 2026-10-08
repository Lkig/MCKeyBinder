# -*- coding: utf-8 -*-
"""界面外观：**现代扁平**的壳 + **MC 灰绿**的配色。

设计取舍
--------
旧版整个界面都照抄 MC 原版贴图（硬边框 + 立体倒角 + 黑底列表），像游戏但不利于
长时间阅读。现在改成：

* 外壳用现代扁平设计 —— 浅灰底、白底扁平按钮、1 像素描边、大量留白、单一强调色；
* 配色仍然是 MC 系 —— 强调色用 MC 的深绿 ``#3C8527``，状态色沿用原版调色板的
  绿 / 红 / 橙 / 蓝 / 黄；
* **唯一的例外是键位图**：那上面的键帽依然是立体倒角的方块（``bevel`` /
  ``sunken``），因为键盘布局本来就是一堆物理按键，倒角在那里是信息而不是装饰。

技术约束
--------
只能继续用 ttk 的 ``clam`` 主题：只有它把 ``bordercolor`` / ``lightcolor`` /
``darkcolor`` 暴露出来，``vista`` 是原生绘制、改不动这些颜色。扁平化正是靠
「把 lightcolor / darkcolor 设成和 background 一样」来干掉 clam 默认的倒角。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# ----------------------------------------------------------------------
# 调色板
# ----------------------------------------------------------------------
# 外壳（现代扁平：浅灰底 + 白面 + 细描边）
BG = "#F7F8FA"             # 窗口 / 面板底色
SURFACE = "#FFFFFF"        # 输入框、列表、选中标签页的「面」
BG_ALT = "#EEF0F3"         # 次级底色（工具条、表头）
BORDER = "#DFE3E8"         # 1px 描边
BORDER_STRONG = "#C3C9D0"
HOVER = "#EDF0F3"          # 悬停
PRESSED = "#E1E5EA"        # 按下

TEXT = "#23272E"
TEXT_DIM = "#6B7280"
TEXT_DISABLED = "#A9AFB7"

# MC 系强调色（深绿是 1.20+ 原版界面的按钮色）
GREEN = "#3C8527"
GREEN_LIGHT = "#4C9E33"
GREEN_DARK = "#2C6419"
GREEN_SOFT = "#E7F4E0"
YELLOW = "#C8A000"
RED = "#B4342A"
RED_LIGHT = "#C9483C"
RED_DARK = "#87241C"
ORANGE = "#B8730E"
BLUE = "#3B6FB6"
GRAY = "#8B8B8B"

# ---- 兼容旧名字（键位图那几个模块还在用） ----
BLACK = "#000000"
FACE = BG                  # 旧代码里的「面板色」→ 现在就是窗口底色
FACE_PRESSED = PRESSED
FACE_DISABLED = "#F1F2F4"
LIGHT = SURFACE
DARK = BORDER
SLOT = "#8B8B8B"           # 物品槽凹陷（键位图仍用）
SLOT_DARK = "#373737"
LIST_BG = SURFACE          # 列表底（现在改成白底）
LIST_FG = TEXT
ACCENT = "#C8A000"         # 原版黄压暗到能在浅底上看清

#: 键位图画布：这是全场唯一保留暗色 + 立体感的地方
CANVAS_BG = "#2E3133"
#: 暗底画布上的说明文字色（浅色主题的 TEXT 是深色，画在暗底上等于看不见）
CANVAS_FG = "#E8EAED"
CANVAS_DIM = "#A6ACB4"

TOOLTIP_BG = "#1F2430"
TOOLTIP_BORDER = "#3C4658"
TOOLTIP_BORDER_DARK = "#12161E"

#: 键位状态 -> (中文名, 填充色, 高光色, 阴影色, 字色)
KEY_STATE_STYLE: dict[str, tuple[str, str, str, str, str]] = {
    "free":     ("空闲",         "#5A5F63", "#71767A", "#3E4245", "#C9CDD1"),
    "used":     ("已绑定",       GREEN,     GREEN_LIGHT, GREEN_DARK, "#FFFFFF"),
    "conflict": ("冲突",         RED,       RED_LIGHT, RED_DARK, "#FFFFFF"),
    "diff":     ("与主配置不同", ORANGE,    "#D9911F", "#7A4C08", "#FFFFFF"),
    "selected": ("已选中",       BLUE,      "#5A8FD6", "#25487A", "#FFFFFF"),
}

#: Treeview 的 tag 配色（浅底 + 深色字，比黑底彩字更好读）
TAG_COLORS: dict[str, dict[str, str]] = {
    "same":     {"background": SURFACE,   "foreground": TEXT},
    "diff":     {"background": "#FFF6E5", "foreground": "#8A5A00"},
    "unbound":  {"background": "#EAF2FB", "foreground": "#1F4E79"},
    "missing":  {"background": SURFACE,   "foreground": "#9AA0A6"},
    "conflict": {"background": "#FDECEA", "foreground": "#A3261B"},
    "changed":  {"background": "#EBF6E6", "foreground": "#2C6B18"},
    "odd":      {"background": SURFACE,   "foreground": "#5F6368"},
    "dim":      {"background": SURFACE,   "foreground": "#9AA0A6"},
    "icon":     {"background": SURFACE,   "foreground": GREEN},
}

PREFERRED_FONTS = ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Segoe UI")


def pick_font(root: tk.Misc) -> str:
    """挑一个系统上存在的中文无衬线字体。"""
    import tkinter.font as tkfont

    available = set(tkfont.families(root))
    return next((f for f in PREFERRED_FONTS if f in available), "TkDefaultFont")


# ----------------------------------------------------------------------
# Canvas 上的立体方块（只有键位图在用）
# ----------------------------------------------------------------------
def bevel(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float,
          face: str = SLOT, light: str = "#B0B0B0", dark: str = "#3E4245",
          border: str = BLACK, b: float = 2, tags: str | tuple = ()) -> None:
    """在 Canvas 上画一个凸起的立体方块（键帽的样子）。"""
    canvas.create_rectangle(x0, y0, x1, y1, fill=border, outline="", tags=tags)
    canvas.create_rectangle(x0 + b, y0 + b, x1 - b, y1 - b, fill=face, outline="", tags=tags)
    canvas.create_rectangle(x0 + b, y0 + b, x1 - b, y0 + 2 * b, fill=light, outline="", tags=tags)
    canvas.create_rectangle(x0 + b, y0 + b, x0 + 2 * b, y1 - b, fill=light, outline="", tags=tags)
    canvas.create_rectangle(x0 + b, y1 - 2 * b, x1 - b, y1 - b, fill=dark, outline="", tags=tags)
    canvas.create_rectangle(x1 - 2 * b, y0 + b, x1 - b, y1 - b, fill=dark, outline="", tags=tags)


def sunken(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float,
           face: str = SLOT, light: str = "#B0B0B0", dark: str = SLOT_DARK,
           border: str = BLACK, b: float = 2, tags: str | tuple = ()) -> None:
    """反过来的立体（凹陷），用于物品槽那种「往里凹」的区域。"""
    canvas.create_rectangle(x0, y0, x1, y1, fill=border, outline="", tags=tags)
    canvas.create_rectangle(x0 + b, y0 + b, x1 - b, y1 - b, fill=face, outline="", tags=tags)
    canvas.create_rectangle(x0 + b, y0 + b, x1 - b, y0 + 2 * b, fill=dark, outline="", tags=tags)
    canvas.create_rectangle(x0 + b, y0 + b, x0 + 2 * b, y1 - b, fill=dark, outline="", tags=tags)
    canvas.create_rectangle(x0 + b, y1 - 2 * b, x1 - b, y1 - b, fill=light, outline="", tags=tags)
    canvas.create_rectangle(x1 - 2 * b, y0 + b, x1 - b, y1 - b, fill=light, outline="", tags=tags)


def mc_text(canvas: tk.Canvas, x: float, y: float, text: str, *,
            fill: str = "#FFFFFF", font=None, anchor: str = "center",
            shadow: str = "#1A1A1A", tags: str | tuple = ()) -> None:
    """带一像素右下阴影的文字 —— 在杂乱的键位图底色上保证可读性。"""
    if shadow:
        canvas.create_text(x + 1, y + 1, text=text, fill=shadow, font=font,
                           anchor=anchor, tags=tags)
    canvas.create_text(x, y, text=text, fill=fill, font=font, anchor=anchor, tags=tags)


# ----------------------------------------------------------------------
# 主题
# ----------------------------------------------------------------------
def apply_theme(root: tk.Misc, base_size: int = 9) -> dict:
    """把 ttk 主题改造成现代扁平外观，返回字体字典。"""
    family = pick_font(root)
    fonts = {
        "base": (family, base_size),
        "bold": (family, base_size, "bold"),
        "title": (family, base_size + 2, "bold"),
        "h1": (family, base_size + 6, "bold"),
        "h2": (family, base_size + 3, "bold"),
        "small": (family, base_size - 1),
        "tiny": (family, base_size - 2),
        "mono": ("Consolas", base_size),
    }

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # 全局默认：浅灰底 + 深色字，倒角色 = 底色（= 没有倒角）
    style.configure(".", font=fonts["base"], background=BG, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=BG, darkcolor=BG,
                    troughcolor=BG_ALT, focuscolor=BG, fieldbackground=SURFACE)

    # ---- 按钮：白底细边扁平，悬停变浅灰 ----
    style.configure("TButton", background=SURFACE, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=SURFACE, darkcolor=SURFACE,
                    relief="flat", borderwidth=1, focusthickness=0,
                    padding=(10, 5), anchor="center")
    style.map("TButton",
              background=[("disabled", FACE_DISABLED), ("pressed", PRESSED),
                          ("active", HOVER)],
              foreground=[("disabled", TEXT_DISABLED)],
              bordercolor=[("disabled", BORDER), ("active", BORDER_STRONG),
                           ("pressed", BORDER_STRONG)],
              lightcolor=[("disabled", FACE_DISABLED), ("pressed", PRESSED),
                          ("active", HOVER)],
              darkcolor=[("disabled", FACE_DISABLED), ("pressed", PRESSED),
                         ("active", HOVER)])

    # 主按钮：MC 深绿
    primary = dict(background=GREEN, foreground="#FFFFFF", bordercolor=GREEN_DARK,
                   lightcolor=GREEN, darkcolor=GREEN, font=fonts["bold"],
                   relief="flat", borderwidth=1, padding=(16, 7))
    style.configure("Primary.TButton", **primary)
    style.map("Primary.TButton",
              background=[("disabled", "#A9C4A0"), ("pressed", GREEN_DARK),
                          ("active", GREEN_LIGHT)],
              foreground=[("disabled", "#F2F5F1")],
              bordercolor=[("disabled", "#A9C4A0"), ("pressed", GREEN_DARK),
                           ("active", GREEN_LIGHT)],
              lightcolor=[("disabled", "#A9C4A0"), ("pressed", GREEN_DARK),
                          ("active", GREEN_LIGHT)],
              darkcolor=[("disabled", "#A9C4A0"), ("pressed", GREEN_DARK),
                         ("active", GREEN_LIGHT)])
    # 旧名字，键位图/对比页里还在用
    style.configure("Accent.TButton", **primary)
    style.map("Accent.TButton", **style.map("Primary.TButton"))

    # 危险按钮（删除类）
    style.configure("Danger.TButton", background=SURFACE, foreground=RED,
                    bordercolor="#E4C4C0", lightcolor=SURFACE, darkcolor=SURFACE,
                    relief="flat", borderwidth=1, padding=(10, 5))
    style.map("Danger.TButton",
              background=[("pressed", "#F7DEDB"), ("active", "#FBEAE8")],
              foreground=[("disabled", TEXT_DISABLED)],
              lightcolor=[("pressed", "#F7DEDB"), ("active", "#FBEAE8")],
              darkcolor=[("pressed", "#F7DEDB"), ("active", "#FBEAE8")])

    # 小号按钮（工具条里那些次要动作）
    style.configure("Small.TButton", padding=(8, 3), font=fonts["small"])
    style.configure("SmallPrimary.TButton", **dict(primary, padding=(12, 5),
                                                   font=fonts["bold"]))
    # ttk 的派生名字只从组件类继承，不会从 "Primary.TButton" 继承，map 要再挂一次
    style.map("SmallPrimary.TButton", **style.map("Primary.TButton"))

    # 「更多 ▾」这类下拉按钮，外观跟普通按钮保持一致
    style.configure("TMenubutton", background=SURFACE, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=SURFACE, darkcolor=SURFACE,
                    relief="flat", borderwidth=1, arrowcolor=TEXT,
                    focusthickness=0, padding=(10, 5))
    style.map("TMenubutton",
              background=[("disabled", FACE_DISABLED), ("pressed", PRESSED),
                          ("active", HOVER)],
              foreground=[("disabled", TEXT_DISABLED)],
              arrowcolor=[("disabled", TEXT_DISABLED)],
              bordercolor=[("disabled", BORDER), ("active", BORDER_STRONG),
                           ("pressed", BORDER_STRONG)],
              lightcolor=[("disabled", FACE_DISABLED), ("pressed", PRESSED),
                          ("active", HOVER)],
              darkcolor=[("disabled", FACE_DISABLED), ("pressed", PRESSED),
                         ("active", HOVER)])
    style.configure("Small.TMenubutton", padding=(8, 3), font=fonts["small"])

    # ---- 输入框 / 下拉框：白底细边 ----
    for name in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(name, fieldbackground=SURFACE, background=SURFACE,
                        foreground=TEXT, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER,
                        arrowcolor=TEXT_DIM, padding=4, relief="flat",
                        borderwidth=1)
    style.map("TEntry", bordercolor=[("focus", GREEN)],
              lightcolor=[("focus", GREEN)], darkcolor=[("focus", GREEN)])
    style.map("TCombobox",
              fieldbackground=[("readonly", SURFACE), ("disabled", BG_ALT)],
              bordercolor=[("focus", GREEN)],
              lightcolor=[("focus", GREEN)], darkcolor=[("focus", GREEN)],
              selectbackground=[("readonly", SURFACE)],
              selectforeground=[("readonly", TEXT)])
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", GREEN_SOFT)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    # ---- 复选框 / 单选框 ----
    # 注意：clam 的 Checkbutton.indicator **不认** indicatorcolor，只认
    # indicatorbackground / indicatorforeground，而它在当前 Tk 上把「选中」
    # 画成一个粗黑的 ✗（见 tests/check_probe.py 的对比截图），完全不能用。
    # 所以这里直接把指示器换成自绘的图像元素，见 check_style()。
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=BG, foreground=TEXT, focusthickness=0,
                        padding=2)
        style.map(name, background=[("active", BG)])

    # ---- 文字 ----
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Title.TLabel", font=fonts["title"], foreground=TEXT)
    style.configure("H1.TLabel", font=fonts["h1"], foreground=TEXT)
    style.configure("H2.TLabel", font=fonts["h2"], foreground=TEXT)
    style.configure("Hint.TLabel", foreground=TEXT_DIM, font=fonts["small"])
    style.configure("Dim.TLabel", foreground=TEXT_DIM)
    style.configure("Accent.TLabel", foreground=GREEN_DARK, font=fonts["bold"])
    style.configure("Danger.TLabel", foreground=RED, font=fonts["bold"])
    style.configure("Warn.TLabel", foreground=ORANGE, font=fonts["bold"])
    style.configure("Mono.TLabel", font=fonts["mono"], foreground=TEXT_DIM)

    # ---- 容器 ----
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=BG)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("Bar.TFrame", background=BG)
    style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, relief="solid",
                    borderwidth=1)
    style.configure("TLabelframe.Label", background=BG, foreground=TEXT_DIM,
                    font=fonts["bold"])
    style.configure("Card.TLabelframe", background=BG, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, relief="solid",
                    borderwidth=1)

    style.configure("TSeparator", background=BORDER)
    style.configure("Sash", sashthickness=8, gripcount=0, background=BG,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.configure("TPanedwindow", background=BG)

    # ---- 滚动条：细、扁平 ----
    style.configure("TScrollbar", background=BG_ALT, troughcolor=BG,
                    bordercolor=BG, lightcolor=BG_ALT, darkcolor=BG_ALT,
                    arrowcolor=TEXT_DIM, relief="flat", borderwidth=0,
                    arrowsize=12, width=10)
    style.map("TScrollbar", background=[("active", BORDER_STRONG),
                                        ("pressed", BORDER_STRONG)])

    # ---- 标签页 ----
    style.configure("TNotebook", background=BG, bordercolor=BG,
                    lightcolor=BG, darkcolor=BG, tabmargins=(4, 6, 4, 0),
                    borderwidth=0, tabposition="nw")
    style.configure("TNotebook.Tab", background=BG, foreground=TEXT_DIM,
                    padding=(12, 7), bordercolor=BG,
                    lightcolor=BG, darkcolor=BG, font=fonts["base"])
    style.map("TNotebook.Tab",
              background=[("selected", SURFACE), ("active", BG_ALT)],
              foreground=[("selected", GREEN_DARK), ("active", TEXT)],
              font=[("selected", fonts["bold"])],
              bordercolor=[("selected", BORDER)],
              lightcolor=[("selected", SURFACE)], darkcolor=[("selected", SURFACE)])

    # ---- 列表：白底深字，表头浅灰 ----
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                    foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, rowheight=26, relief="flat",
                    borderwidth=1, font=fonts["base"])
    style.map("Treeview", background=[("selected", GREEN_SOFT)],
              foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=BG_ALT, foreground=TEXT_DIM,
                    font=fonts["bold"], relief="flat", borderwidth=0,
                    bordercolor=BORDER, lightcolor=BG_ALT, darkcolor=BG_ALT,
                    padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", HOVER)],
              foreground=[("active", TEXT)])

    # ---- 进度条 ----
    style.configure("Horizontal.TProgressbar", background=GREEN,
                    troughcolor=BG_ALT, bordercolor=BG_ALT,
                    lightcolor=GREEN, darkcolor=GREEN, thickness=6,
                    borderwidth=0)
    style.configure("Status.Horizontal.TProgressbar", background=GREEN,
                    troughcolor=BG_ALT, bordercolor=BG_ALT,
                    lightcolor=GREEN, darkcolor=GREEN, thickness=4,
                    borderwidth=0)

    root.configure(background=BG)
    return fonts


def card(parent: tk.Misc, title: str | None = None, **kwargs) -> ttk.Frame:
    """一个「卡片」容器：1 像素描边的浅色分组框。

    比 ``ttk.Labelframe`` 好控制的地方是标题自己排版，能塞进副标题或按钮。
    """
    outer = ttk.Frame(parent, style="Card.TFrame", **kwargs)
    if title:
        ttk.Label(outer, text=title, style="Dim.TLabel").pack(
            anchor="w", padx=10, pady=(8, 0))
    return outer


# ----------------------------------------------------------------------
# 复选框：自己画指示器
# ----------------------------------------------------------------------
_CHECK_CACHE: dict[str, tk.PhotoImage] = {}
_CHECK_STYLES: set[str] = set()


def _check_image(master: tk.Misc, fill: str, checked: bool, size: int = 14,
                 gap: int = 5) -> tk.PhotoImage:
    """画一个方框；``checked`` 时在框里画对勾。

    ``gap`` 是方框右边留出的透明像素：ttk 的 layout 不接受 ``padding``，
    只好把间距画进图片里，免得方框和文字贴在一起。
    """
    key = f"{fill}|{checked}|{size}|{gap}"
    cached = _CHECK_CACHE.get(key)
    if cached is not None:
        return cached

    img = tk.PhotoImage(master=master, width=size + gap, height=size)
    # 外框（1px 描边）+ 内部填充
    img.put(BORDER_STRONG, to=(0, 0, size, 1))
    img.put(BORDER_STRONG, to=(0, size - 1, size, size))
    img.put(BORDER_STRONG, to=(0, 0, 1, size))
    img.put(BORDER_STRONG, to=(size - 1, 0, size, size))
    # 未选中时填浅灰：纯白底 + 浅描边在白卡片上几乎看不出是个框
    img.put(SURFACE if checked else BG_ALT, to=(1, 1, size - 1, size - 1))
    if checked:
        img.put(fill, to=(1, 1, size - 1, size - 1))
        # 对勾：在 (3,7)-(5,9)-(10,4) 上走两段粗线
        pts = [(3, 7), (4, 8), (6, 10), (7, 9), (10, 4), (11, 3)]
        stroke = "#FFFFFF" if fill != "#FFFFFF" else TEXT
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            steps = max(abs(x1 - x0), abs(y1 - y0), 1)
            for s in range(steps + 1):
                x = round(x0 + (x1 - x0) * s / steps)
                y = round(y0 + (y1 - y0) * s / steps)
                img.put(stroke, to=(x, y, x + 2, y + 2))

    _CHECK_CACHE[key] = img
    return img


def check_style(style: ttk.Style, color: str = GREEN) -> str:
    """注册（或复用）一个 TCheckbutton 风格：指示器是自绘的方框。

    选中时方框填充 ``color``，用于把过滤器勾选框染成对应的状态色。
    返回风格名，传给 ``ttk.Checkbutton(style=...)`` 即可。
    """
    key = color.lstrip("#").upper()
    name = f"MC{key}.TCheckbutton"
    if name in _CHECK_STYLES:
        return name

    master = style.master
    off_img = _check_image(master, SURFACE, False)
    on_img = _check_image(master, color, True)
    element = f"MC{key}.Check.indicator"
    try:
        style.element_create(element, "image", off_img,
                             ("selected", on_img), ("disabled", off_img),
                             ("disabled", "selected", on_img),
                             border=0, sticky="")
    except tk.TclError:
        pass  # 已经注册过
    style.layout(name, [
        ("Checkbutton.padding", {"sticky": "nswe", "children": [
            (element, {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nswe"})]}),
        ]}),
    ])
    style.configure(name, background=BG, foreground=TEXT, focusthickness=0,
                    padding=(2, 1), bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.map(name,
              background=[("active", BG), ("disabled", BG)],
              foreground=[("disabled", TEXT_DISABLED), ("active", TEXT)],
              lightcolor=[("active", BG)], darkcolor=[("active", BG)])
    _CHECK_STYLES.add(name)
    return name


# ----------------------------------------------------------------------
# 提示框
# ----------------------------------------------------------------------
class Tooltip:
    """扁平风格的浮动提示：深灰底、浅边、白字。"""

    def __init__(self, widget: tk.Misc, delay: int = 400) -> None:
        self.widget = widget
        self.delay = delay
        self._after: str | None = None
        self._tip: tk.Toplevel | None = None

    def schedule(self, text: str, x: int | None = None, y: int | None = None) -> None:
        self.cancel()
        if not text:
            return
        self._after = self.widget.after(self.delay, lambda: self._show(text, x, y))

    def cancel(self) -> None:
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        self.hide()

    def hide(self) -> None:
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None

    def _show(self, text: str, x: int | None, y: int | None) -> None:
        if self._tip is not None:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        outer = tk.Frame(tip, background=TOOLTIP_BORDER_DARK, borderwidth=0)
        outer.pack()
        inner = tk.Frame(outer, background=TOOLTIP_BORDER, borderwidth=0)
        inner.pack(padx=1, pady=1)
        tk.Label(inner, text=text, background=TOOLTIP_BG, foreground="#FFFFFF",
                 justify="left", anchor="w", padx=8, pady=4,
                 font=("Microsoft YaHei UI", 9)).pack()

        if x is None or y is None:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tip.wm_geometry(f"+{x + 12}+{y + 12}")
        self._tip = tip
