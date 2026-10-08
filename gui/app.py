# -*- coding: utf-8 -*-
"""MCKeyBinder 按键同步器 —— 图形界面主窗口。

界面结构::

    ┌ 顶栏：品牌 ────────────────────────── [预览变更] [★ 一键同步] ┐
    │      主配置（方案）：[下拉] [抓取] [保存方案] [导入方案] [更多▾] │
    ├────────────────┬──────────────────────────────────────────────┤
    │ 实例列表        │ 标签页：键位图 / 按键对比 / 其他设置 /        │
    │ （可拖拽宽度）   │        模组配置 / 备份 / 同步选项             │
    │                │ 每页顶部：本页筛选 ┈┈ [保存方案][导入方案][同步]│
    ├────────────────┴──────────────────────────────────────────────┤
    │ 运行日志（可拖拽高度、可折叠）                                   │
    ├───────────────────────────────────────────────────────────────┤
    │ 状态栏 + 进度条                                                │
    └───────────────────────────────────────────────────────────────┘

窗口尺寸、位置、两处分栏的拖拽位置、上次选中的标签页都会存进 ``Settings.ui``，
下次启动原样恢复（见 ``_restore_ui`` / ``_save_ui``）。

所有耗时操作（磁盘扫描、mod 扫描、写文件）都放在后台线程里，通过队列回传进度，
避免界面卡死。
"""

from __future__ import annotations

import queue
import sys
import threading
import traceback
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcsync import APP_NAME, __version__
from mcsync.app import App
from mcsync.diff import CHANGE_META, ChangeKind, DiffTable
from mcsync.instances import Instance
from mcsync.optionsfile import DEFAULT_SYNCED_OPTIONS, INSTANCE_SPECIFIC_OPTIONS
from mcsync.profile import Profile
from mcsync.resources import resource_dir
from mcsync.sync import SyncPlan, SyncPolicy

try:                                        # 正常包导入（main.py / python -m gui.app）
    from . import mcstyle
    from .keymap_tab import KeymapTab
    from .widgets import CheckTree, LogPane, ScrollFrame
except ImportError:                         # 直接 `python gui/app.py` 运行时没有包上下文
    from gui import mcstyle
    from gui.keymap_tab import KeymapTab
    from gui.widgets import CheckTree, LogPane, ScrollFrame

PREFERRED_FONTS = ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Segoe UI")

#: 状态 -> (显示文字, Treeview tag)
KIND_STYLE: dict[ChangeKind, tuple[str, str]] = {
    ChangeKind.SAME: ("一致", "same"),
    ChangeKind.DIFFERS: ("不一致", "diff"),
    ChangeKind.TARGET_UNBOUND: ("目标未绑定", "unbound"),
    ChangeKind.PROFILE_UNBOUND: ("将设为未绑定", "unbound"),
    ChangeKind.ONLY_IN_TARGET: ("仅目标有", "missing"),
    ChangeKind.ONLY_IN_PROFILE: ("目标没有", "missing"),
    ChangeKind.SEMANTIC: ("同功能对齐", "changed"),
}

#: 同步范围：整页/全局、只按键、只其他设置
SCOPE_ALL = "all"
SCOPE_KEYBINDS = "keybinds"
SCOPE_OPTIONS = "options"


class SyncApp(tk.Tk):
    """主窗口。

    ``autostart=False`` 时不会自动扫描（测试与嵌入场景用），避免启动就弹对话框。
    """

    def __init__(self, app: App, autostart: bool = True) -> None:
        super().__init__()
        self.app = app

        self.title(f"{APP_NAME}  v{__version__}")
        self.minsize(1120, 680)
        self._set_icon()

        self.instances: list[Instance] = []
        self.instance_by_key: dict[str, Instance] = {}
        self.profile: Profile | None = None
        self.diff_table: DiffTable | None = None
        self.last_plan: SyncPlan | None = None
        self.selected_options: dict[str, tk.BooleanVar] = {}
        self.config_candidates: list = []
        self._jobs: queue.Queue = queue.Queue()
        self._busy = False
        self._key_count_cache: dict[str, tuple[tuple[float, int], str]] = {}
        self._normal_geometry = ""       # 未最大化时的窗口尺寸位置，用来存盘
        self._ui_ready = False           # 避免恢复界面状态时把脏数据写回去
        self._options_lang_ready = False  # 『其他设置』是否已经拿到原版中文语言表

        self._init_style()
        self._build_topbar()
        self._build_body()
        self._build_statusbar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_configure)
        self.after(60, self._poll_jobs)
        self._restore_ui()
        self._ui_ready = True

        self.log("欢迎使用 MCKeyBinder 按键同步器。", "ok")
        self.log("这个工具直接改各整合包的 options.txt，不需要往任何整合包里装 Mod。", "dim")
        self.log("先点左侧的『扫描实例』，它会自动找出机器上的整合包。", "dim")
        if autostart:
            # 启动时先做一次快速扫描（只查常见启动器路径，不会弹窗、不会扫盘）。
            # 想全盘找装在自定义路径的整合包，点『扫描实例』即可。
            self.after(200, lambda: self._do_scan(False))

    # ------------------------------------------------------------------
    # 外观
    # ------------------------------------------------------------------
    def _set_icon(self) -> None:
        """给窗口装上项目自带的图标（``assets/app.ico``，退回 png）。"""
        assets = resource_dir() / "assets"
        ico = assets / "app.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
                self.iconbitmap(default=str(ico))  # 让子弹窗也继承同一个图标
                return
            except tk.TclError:
                pass
        png = assets / "app_256.png"
        if png.exists():
            try:
                # 必须留个引用，否则 PhotoImage 会被回收，图标变空白
                self._icon_img = tk.PhotoImage(file=str(png))
                self.iconphoto(True, self._icon_img)
            except tk.TclError:
                pass

    def _init_style(self) -> None:
        # 现代扁平主题 + MC 的灰/绿配色（见 gui/mcstyle.py）。
        self.fonts = mcstyle.apply_theme(self, base_size=9)
        self.base_font = self.fonts["base"]
        self.bold_font = self.fonts["bold"]

    # ------------------------------------------------------------------
    # 界面状态的记忆与恢复
    # ------------------------------------------------------------------
    def _on_configure(self, event=None) -> None:
        """记住「未最大化」时的窗口尺寸位置，最大化状态下不要覆盖它。"""
        if not self._ui_ready or (event is not None and event.widget is not self):
            return
        try:
            if self.state() == "normal":
                self._normal_geometry = self.geometry()
        except tk.TclError:
            pass

    def _default_geometry(self) -> str:
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        w = max(940, min(1240, screen_w - 160))
        h = max(600, min(800, screen_h - 160))
        x = max(0, (screen_w - w) // 2)
        y = max(0, (screen_h - h) // 3)
        return f"{w}x{h}+{x}+{y}"

    def _geometry_on_screen(self, geometry: str) -> bool:
        """确认存下来的窗口位置还落在当前屏幕里（换显示器后别把窗口丢到屏幕外）。"""
        import re

        match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", str(geometry).strip())
        if not match:
            return False
        w, h, x, y = (int(g) for g in match.groups())
        if w < 600 or h < 400:
            return False
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        return (-w + 120) < x < (screen_w - 120) and (-h + 120) < y < (screen_h - 120)

    def _restore_ui(self) -> None:
        ui = self.app.settings.ui
        geometry = str(ui.get("window_geometry") or "")
        if geometry and self._geometry_on_screen(geometry):
            try:
                self.geometry(geometry)
                self._normal_geometry = geometry
            except tk.TclError:
                self.geometry(self._default_geometry())
        else:
            self.geometry(self._default_geometry())

        if ui.get("window_maximized"):
            try:
                self.state("zoomed")
            except tk.TclError:
                pass

        tab = str(self.app.settings.get_ui("tab", ""))
        if tab:
            self._select_tab_text(tab)
        if ui.get("log_visible") is False:
            self._toggle_log(False)
        # 分栏位置要等窗口真正布局完才能设
        self.after(180, self._restore_sashes)

    def _restore_sashes(self) -> None:
        try:
            self.update_idletasks()
        except tk.TclError:
            return
        # 没有存过位置时，下半条左右平分：左实例、右日志
        if not isinstance(self.app.settings.ui.get("sash_lower"), int):
            try:
                total = self.lower_pane.winfo_width()
                if total > 400:
                    self.lower_pane.sashpos(0, min(820, max(420, int(total * 0.5))))
            except tk.TclError:
                pass
        if not isinstance(self.app.settings.ui.get("sash_band"), int):
            # 主分栏：标签页占上面约七成，下面留一条给实例 + 日志
            try:
                total = self.main_pane.winfo_height()
                if total > 300:
                    self.main_pane.sashpos(0, int(total * 0.72))
            except tk.TclError:
                pass
        for pane, key in ((self.lower_pane, "sash_lower"), (self.main_pane, "sash_band")):
            pos = self.app.settings.ui.get(key)
            if not isinstance(pos, int) or pos <= 0:
                continue
            try:
                horizontal = str(pane.cget("orient")) == "horizontal"
            except tk.TclError:
                continue
            total = pane.winfo_width() if horizontal else pane.winfo_height()
            if pos >= total - 80:      # 别把某一块压没了
                continue
            try:
                pane.sashpos(0, pos)
            except tk.TclError:
                pass

    def _save_ui(self) -> None:
        ui = self.app.settings.ui
        geometry = self._normal_geometry
        if not geometry:
            try:
                if self.state() == "normal":
                    geometry = self.geometry()
            except tk.TclError:
                geometry = ""
        if geometry:
            ui["window_geometry"] = geometry
        try:
            ui["window_maximized"] = self.state() == "zoomed"
        except tk.TclError:
            pass
        for pane, key in ((self.lower_pane, "sash_lower"), (self.main_pane, "sash_band")):
            try:
                ui[key] = int(pane.sashpos(0))
            except (tk.TclError, IndexError):
                pass
        try:
            ui["tab"] = self.notebook.tab(self.notebook.select(), "text")
        except tk.TclError:
            pass
        ui["log_visible"] = bool(self.log_toggle_var.get())
        try:
            self.app.save_settings()
        except OSError:
            pass

    def _select_tab_text(self, text: str) -> None:
        for tab_id in self.notebook.tabs():
            if self.notebook.tab(tab_id, "text") == text:
                self.notebook.select(tab_id)
                return

    def _toggle_log(self, show: bool | None = None) -> None:
        if show is None:
            show = not self.log_toggle_var.get()
        self.log_toggle_var.set(bool(show))
        try:
            if show:
                if not self.log_card.winfo_ismapped():
                    self.lower_pane.add(self.log_card, weight=1)
                self.log_visible_button.configure(text="隐藏日志")
            else:
                self.lower_pane.forget(self.log_card)
                self.log_visible_button.configure(text="显示日志")
        except tk.TclError:
            pass

    def _build_topbar(self) -> None:
        bar = ttk.Frame(self, padding=(14, 12, 14, 10))
        bar.pack(fill="x")

        top = ttk.Frame(bar)
        top.pack(fill="x")
        brand = ttk.Frame(top)
        brand.pack(side="left")
        ttk.Label(brand, text="MCKeyBinder", style="H1.TLabel").pack(anchor="w")
        ttk.Label(brand, text="把一套按键设置一键同步到所有整合包，不用往整合包里装 Mod",
                  style="Hint.TLabel").pack(anchor="w", pady=(2, 0))

        actions = ttk.Frame(top)
        actions.pack(side="right", anchor="ne")
        self.sync_button = ttk.Button(actions, text="一键同步", style="Primary.TButton",
                                      command=self.on_sync)
        self.sync_button.pack(side="right")
        ttk.Button(actions, text="预览变更", command=self.on_preview).pack(side="right", padx=(0, 8))

        ttk.Separator(bar).pack(fill="x", pady=(10, 8))

        row = ttk.Frame(bar)
        row.pack(fill="x")
        ttk.Label(row, text="主配置（方案）").pack(side="left")

        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(row, textvariable=self.profile_var,
                                          state="readonly", width=24)
        self.profile_combo.pack(side="left", padx=(8, 0))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_profile_selected())
        ttk.Button(row, text="从实例抓取…", command=self.on_capture).pack(side="left", padx=(6, 0))

        ttk.Separator(row, orient="vertical").pack(side="left", fill="y", padx=12)

        ttk.Button(row, text="保存方案", command=self.on_save_profile).pack(side="left")
        ttk.Button(row, text="导入方案", command=self.on_import_profile).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="导出方案", command=self.on_export_profile).pack(side="left", padx=(6, 0))

        more = ttk.Menubutton(row, text="更多")
        menu = tk.Menu(more, tearoff=False)
        menu.add_command(label="重命名主配置…", command=self.on_rename_profile)
        menu.add_command(label="删除主配置", command=self.on_delete_profile)
        menu.add_separator()
        menu.add_command(label="添加整合包目录…", command=self.on_add_dir)
        menu.add_command(label="打开数据目录", command=self.on_open_data)
        menu.add_command(label="打开备份目录", command=self.on_open_backups)
        more["menu"] = menu
        more.pack(side="left", padx=(6, 0))

    def _build_body(self) -> None:
        # 竖直分栏：上面整幅给标签页（键位图因此能铺满宽度），
        # 下面一条横着劈成两半——左边挑整合包，右边看日志。两处都能拖、都会记住位置。
        self.main_pane = ttk.PanedWindow(self, orient="vertical")
        self.main_pane.pack(fill="both", expand=True, padx=14)

        nb_wrap = ttk.Frame(self.main_pane, padding=(0, 0, 0, 8))
        self.notebook = ttk.Notebook(nb_wrap)
        self.notebook.pack(fill="both", expand=True)

        # 实例列表虽然在下半条，但标签页构造时要用它算列名，所以先建。
        self.lower_pane = ttk.PanedWindow(self.main_pane, orient="horizontal")
        self._build_instance_panel(self.lower_pane)

        # ---- 日志（可以整块收起来） ----
        self.log_card = ttk.Frame(self.lower_pane, padding=(12, 0, 0, 0))
        head = ttk.Frame(self.log_card)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="运行日志", style="H2.TLabel").pack(side="left")
        ttk.Button(head, text="清空", style="Small.TButton",
                   command=lambda: self.log_pane.clear()).pack(side="right")
        self.log_pane = LogPane(self.log_card, height=4)
        self.log_pane.pack(fill="both", expand=True)
        self.lower_pane.add(self.log_card, weight=1)

        self._build_keymap_tab()
        self._build_keybind_tab()
        self._build_options_tab()
        self._build_config_tab()
        self._build_backup_tab()
        self._build_settings_tab()

        # 切到「备份与还原」时自动列一次，免得看到一片空白以为没有备份
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.main_pane.add(nb_wrap, weight=5)
        self.main_pane.add(self.lower_pane, weight=2)

        self.log_toggle_var = tk.BooleanVar(value=True)

    def _on_tab_changed(self, _event=None) -> None:
        """切标签页时的按需刷新。"""
        try:
            current = self.nametowidget(self.notebook.select())
        except (tk.TclError, KeyError):
            return
        if current is getattr(self, "backup_tab", None):
            self.refresh_backups()

    def _build_instance_panel(self, parent) -> None:
        left = ttk.Frame(parent)

        head = ttk.Frame(left)
        head.pack(fill="x", pady=(0, 6))
        ttk.Label(head, text="整合包 / 实例", style="H2.TLabel").pack(side="left")
        # 下半条本来就矮，把「扫描/添加」并到标题这一行，给列表多留一行高度
        ttk.Button(head, text="添加目录…", style="Small.TButton",
                   command=self.on_add_dir).pack(side="right")
        ttk.Button(head, text="扫描实例", style="Small.TButton",
                   command=self.on_scan).pack(side="right", padx=(0, 6))

        columns = [
            ("check", "选", 32),
            ("name", "名称", 160),
            ("version", "版本", 104),
            ("keys", "按键", 46),
            ("state", "状态", 56),
        ]
        self.instance_tree = CheckTree(left, columns, on_toggle=lambda *_: self.on_instance_toggle(),
                                       height=6)
        self.instance_tree.pack(fill="both", expand=True)
        self.instance_tree.tree.bind("<Double-1>", self._on_instance_double_click)

        foot = ttk.Frame(left)
        foot.pack(fill="x", pady=(6, 0))
        ttk.Button(foot, text="全选", style="Small.TButton",
                   command=lambda: self._set_all_instances(True)).pack(side="left")
        ttk.Button(foot, text="全不选", style="Small.TButton",
                   command=lambda: self._set_all_instances(False)).pack(side="left", padx=4)
        ttk.Button(foot, text="反选", style="Small.TButton",
                   command=self._invert_instances).pack(side="left")
        self.instance_count_var = tk.StringVar(value="已选 0 / 0")
        ttk.Label(foot, textvariable=self.instance_count_var,
                  style="Hint.TLabel").pack(side="right")

        parent.add(left, weight=1)

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, padding=(14, 6, 14, 10))
        bar.pack(fill="x")
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bar, textvariable=self.status_var, style="Hint.TLabel").pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=200)
        self.progress.pack(side="left", padx=12)

        self.log_visible_button = ttk.Button(bar, text="隐藏日志", style="Small.TButton",
                                             command=self._toggle_log)
        self.log_visible_button.pack(side="right")
        ttk.Button(bar, text="刷新对比", style="Small.TButton",
                   command=self.refresh_diff).pack(side="right", padx=(0, 6))

    def _page_actions(self, row: ttk.Frame, sync_command, sync_text: str = "本页同步",
                      sync_style: str = "SmallPrimary.TButton") -> None:
        """标签页工具条右侧的「本页」动作，样式比顶栏的全局按钮小一号。

        不写「本页：」这种前缀标签——窄窗口下这些按钮很容易被挤出可视区。
        """
        box = ttk.Frame(row)
        box.pack(side="right")
        ttk.Button(box, text="保存方案", style="Small.TButton",
                   command=self.on_save_profile).pack(side="left")
        ttk.Button(box, text="导入方案", style="Small.TButton",
                   command=self.on_import_profile).pack(side="left", padx=(4, 0))
        ttk.Button(box, text=sync_text, style=sync_style,
                   command=sync_command).pack(side="left", padx=(4, 0))

    def _build_keymap_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="键位图")
        self.keymap_tab = KeymapTab(tab, self)
        self.keymap_tab.pack(fill="both", expand=True)

    def _build_keybind_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=(10, 8, 10, 8))
        self.notebook.add(tab, text="按键对比")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(toolbar, text="刷新对比", style="Small.TButton",
                   command=self.refresh_diff).pack(side="left")
        ttk.Button(toolbar, text="全选有差异的", style="Small.TButton",
                   command=lambda: self._select_diff_rows(True)).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="全不选", style="Small.TButton",
                   command=lambda: self._select_diff_rows(False)).pack(side="left", padx=(4, 0))
        self.only_diff_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="只看有差异的", variable=self.only_diff_var,
                        style=mcstyle.check_style(ttk.Style(self), mcstyle.ACCENT),
                        command=self.refresh_diff).pack(side="left", padx=(12, 0))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Label(toolbar, text="筛选：", style="Hint.TLabel").pack(side="left", padx=(12, 2))
        ttk.Entry(toolbar, textvariable=self.filter_var, width=16).pack(side="left")

        self._page_actions(toolbar, self.on_sync_selected_keybinds, "同步选中按键")

        # 树 / 详情上下分栏，可以拖动高度
        self.keybind_pane = ttk.PanedWindow(tab, orient="vertical")
        self.keybind_pane.pack(fill="both", expand=True)

        tree_box = ttk.Frame(self.keybind_pane)
        self.keybind_tree = CheckTree(tree_box, self._keybind_columns(),
                                      on_toggle=self._on_keybind_toggle, height=14)
        self.keybind_tree.pack(fill="both", expand=True)
        self.keybind_tree.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_keybind_detail())
        self.keybind_pane.add(tree_box, weight=4)

        detail_box = ttk.Frame(self.keybind_pane, padding=(0, 8, 0, 0))
        self.keybind_detail = ttk.Label(detail_box, text="选中一行可以看到这个功能的说明。",
                                        style="Hint.TLabel", justify="left", anchor="w")
        self.keybind_detail.pack(fill="x")
        self.keybind_pane.add(detail_box, weight=1)

    def _keybind_columns(self) -> list[tuple[str, str, int]]:
        columns = [
            ("check", "选", 38),
            ("group", "分类", 130),
            ("name", "按键", 210),
            ("profile", "主配置", 110),
        ]
        for instance in self._selected_instances():
            columns.append((f"i_{instance.key}", _short(instance.name), 110))
        return columns

    def _build_options_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="其他设置")

        hint = ttk.Label(
            tab,
            text="这些是 options.txt 里按键之外的设置（视野、界面尺寸、最大帧率、鼠标灵敏度……）。"
                 "带「推荐」标记的默认就勾上；标着「实例相关，通常不该同步」的"
                 "（分辨率、资源包、教程进度等）不要跟着同步到别的整合包。"
                 "中文名取自当前 MC 版本的原版语言文件。",
            style="Hint.TLabel", wraplength=620, justify="left")
        hint.pack(fill="x", pady=(0, 6))

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=(0, 6))
        ttk.Button(buttons, text="刷新", style="Small.TButton",
                   command=self.refresh_options).pack(side="left")
        ttk.Button(buttons, text="全选", style="Small.TButton",
                   command=lambda: self._select_options(True)).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="全不选", style="Small.TButton",
                   command=lambda: self._select_options(False)).pack(side="left", padx=(4, 0))
        ttk.Button(buttons, text="仅危险项以外全选", style="Small.TButton",
                   command=self._select_safe_options).pack(side="left", padx=(4, 0))

        self._page_actions(buttons, self.on_sync_options, "同步其他设置")

        # 顶上那个「一键同步」默认只同步按键。用户在这页勾了设置却按「一键同步」时，
        # 很容易以为设置也跟着同步了——这里放一条会实时变色的提示 + 一键打开。
        self.options_note = ttk.Frame(tab)
        self.options_note.pack(fill="x", pady=(0, 6))
        self.options_note_label = ttk.Label(
            self.options_note, text="", style="Hint.TLabel",
            wraplength=620, justify="left")
        self.options_note_label.pack(fill="x")
        self.options_note_button = ttk.Button(
            self.options_note, text="让「一键同步」也同步本页设置", style="Small.TButton",
            command=self.on_enable_options_in_all)

        self.options_container = ScrollFrame(tab)
        self.options_container.pack(fill="both", expand=True)
        self._option_rows: dict[str, tuple[tk.BooleanVar, str]] = {}

    def _build_config_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=(10, 8, 10, 8))
        self.notebook.add(tab, text="模组配置文件")

        ttk.Label(
            tab,
            text="绝大多数模组的按键都在 options.txt 里（上面那个标签页就能同步）。"
                 "但少数模组把自己的快捷键存在独立配置文件里，这里可以扫描并整文件复制。",
            style="Hint.TLabel", wraplength=760, justify="left").pack(fill="x", pady=(0, 6))

        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="源实例：", style="Hint.TLabel").pack(side="left")
        self.config_source_var = tk.StringVar()
        self.config_source_combo = ttk.Combobox(row, textvariable=self.config_source_var,
                                                state="readonly", width=32)
        self.config_source_combo.pack(side="left")
        ttk.Button(row, text="扫描配置文件", style="Small.TButton",
                   command=self.on_scan_configs).pack(side="left", padx=6)
        ttk.Button(row, text="同步选中文件到已勾选实例", style="SmallPrimary.TButton",
                   command=self.on_sync_configs).pack(side="left")

        self.config_tree = CheckTree(tab, [
            ("check", "选", 38),
            ("path", "文件（相对实例目录）", 460),
            ("fields", "疑似快捷键项", 300),
        ], height=14)
        self.config_tree.pack(fill="both", expand=True, pady=(6, 0))

    def _build_backup_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=(10, 8, 10, 8))
        self.notebook.add(tab, text="备份与还原")
        self.backup_tab = tab

        ttk.Label(
            tab,
            text="每次写入前都会自动备份。还原之前，当前文件也会再被备份一次，"
                 "所以「还原错了」不是一个不可逆操作。",
            style="Hint.TLabel", wraplength=760, justify="left").pack(fill="x", pady=(0, 6))

        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(0, 6))
        ttk.Button(row, text="刷新", style="Small.TButton",
                   command=self.refresh_backups).pack(side="left")
        ttk.Button(row, text="还原选中备份", style="Small.TButton",
                   command=self.on_restore_backup).pack(side="left", padx=6)
        ttk.Button(row, text="删除选中备份", style="Small.TButton",
                   command=self.on_delete_backup).pack(side="left")
        ttk.Button(row, text="打开备份文件夹", style="Small.TButton",
                   command=self.on_open_backups).pack(side="left", padx=6)
        ttk.Button(row, text="全选", style="Small.TButton",
                   command=lambda: self.backup_tree.tree.selection_set(
                       self.backup_tree.tree.get_children())).pack(side="left")
        ttk.Button(row, text="取消选择", style="Small.TButton",
                   command=lambda: self.backup_tree.tree.selection_remove(
                       *self.backup_tree.tree.selection())).pack(side="left", padx=6)
        ttk.Label(row, text="可以 Shift 连选、Ctrl 挑着选", style="Hint.TLabel").pack(
            side="left", padx=(10, 0))

        # link_selection：勾选跟着选择走（点一下打勾、Ctrl 挑单个、Shift 连选）
        self.backup_tree = CheckTree(tab, [
            ("check", "", 38),
            ("time", "时间", 170),
            ("label", "说明", 190),
            ("files", "文件数", 70),
            ("size", "大小", 90),
        ], height=16, selectmode="extended", link_selection=True)
        self.backup_tree.pack(fill="both", expand=True, pady=(6, 0))

    def _build_settings_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="同步选项")

        self.policy_vars: dict[str, tk.BooleanVar] = {}

        def add(key: str, title: str, detail: str, default: bool) -> None:
            # 用设置里存着的值初始化，而不是写死的默认值——
            # 否则用户改过的开关一重启就变回默认，下一次同步还会把默认值写回去。
            saved = getattr(self.app.settings, key, default)
            var = tk.BooleanVar(value=bool(saved))
            self.policy_vars[key] = var
            ttk.Checkbutton(tab, text=title, variable=var,
                            style=mcstyle.check_style(ttk.Style(self), mcstyle.GREEN)
                            ).pack(anchor="w", pady=(6, 0))
            ttk.Label(tab, text=detail, style="Hint.TLabel",
                      wraplength=720, justify="left").pack(anchor="w", padx=(22, 0))

        add("semantic_sync", "跨 Mod 同功能对齐",
            "主配置里是 Aero 小地图的「打开世界地图」，目标整合包装的是 JourneyMap 时，"
            "也能把 JourneyMap 的对应按键一起改成同样的键。", True)
        add("sync_options", "同时同步「其他设置」",
            "同步你在『其他设置』标签页里勾选的项（视野、GUI 缩放、音量……）。", False)
        add("write_default_targets", "同时写入整合包的默认值文件",
            "把键位也写进 configureddefaults / defaultoptions / kubejs 等目录。"
            "好处是整合包更新重置了设置、或以后新建同类实例时，仍然是你的键位。", False)
        add("sync_optifine", "同时同步 OptiFine 的 optionsof.txt",
            "OptiFine 自己存了一份缩放键（旧式数字键码）。装了 OptiFine 的实例才有效。", False)
        add("convert_legacy", "自动适配 1.12 等旧版的数字键码",
            "把现代键码转成旧版数字（如空格 -> 57）。旧版表达不了的修饰键组合会被跳过。", True)
        add("skip_unbind", "不把目标已绑定的键改成「未绑定」",
            "避免主配置里某个「未绑定」的项把目标实例里已经设好的键清掉。", True)
        add("respect_manual_changes", "不覆盖你手动改过的按键",
            "同步过一次之后就有基线了：如果你在某个整合包里把某个键解绑、"
            "或改成了别的键，下次同步会保留你的改动，不再按主配置绑回去。"
            "关掉它就每次都强制对齐主配置。", True)
        add("include_unknown_keybinds", "目标没有的按键也写入（不推荐）",
            "Minecraft 退出时会重写 options.txt 并且只保留它认识的项，写进去的未知按键"
            "会被静默删除——除非那个整合包确实装了对应 Mod 且还没启动过。", False)

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=14)
        ttk.Label(tab, text="数据目录", style="H2.TLabel").pack(anchor="w")
        ttk.Label(tab, text=str(self.app.data_dir), style="Hint.TLabel",
                  wraplength=720, justify="left").pack(anchor="w", pady=(2, 0))
        ttk.Label(tab, text="主配置、备份、缓存都放在这里。可以把整个文件夹拷走做迁移。",
                  style="Hint.TLabel", wraplength=720,
                  justify="left").pack(anchor="w")

        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=14)
        ttk.Label(tab, text="同步基线", style="H2.TLabel").pack(anchor="w")
        ttk.Label(tab, text="每次同步结束后，工具会记下目标整合包当时的键位，"
                            "用来判断「哪些键是你后来自己改的」。"
                            "想彻底忘掉这些记录、让下次同步强推主配置，就点右边的按钮。",
                  style="Hint.TLabel", wraplength=700,
                  justify="left").pack(side="left", anchor="w", pady=(2, 0))
        ttk.Button(tab, text="重置同步基线", style="Small.TButton",
                   command=self.on_reset_state).pack(side="left", padx=10)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def log(self, message: str, tag: str = "") -> None:
        self.log_pane.log(message, tag)

    def set_status(self, text: str, busy: bool = False) -> None:
        self.status_var.set(text)
        if busy and not self._busy:
            self._busy = True
            self.progress.start(12)
        elif not busy and self._busy:
            self._busy = False
            self.progress.stop()

    def _selected_instances(self) -> list[Instance]:
        return [self.instance_by_key[iid]
                for iid in self.instance_tree.checked_items()
                if iid in self.instance_by_key]

    #: 给子控件（键位图标签页）用的公开别名
    def selected_instances(self) -> list[Instance]:
        return self._selected_instances()

    def save_profile(self, profile: Profile) -> None:
        """把改过的主配置落盘，并刷新下拉框。"""
        self.app.save_profile(profile)
        self._refresh_profile_combo()

    def _set_all_instances(self, checked: bool) -> None:
        self.instance_tree.set_all_checked(checked)
        self._update_instance_count()
        self.refresh_diff()

    def _invert_instances(self) -> None:
        for iid in self.instance_tree.all_items():
            self.instance_tree.set_checked(iid, not self.instance_tree.is_checked(iid))
        self._update_instance_count()
        self.refresh_diff()

    def on_instance_toggle(self) -> None:
        self._update_instance_count()
        self.refresh_diff()

    def _on_instance_double_click(self, _event) -> None:
        selection = self.instance_tree.tree.selection()
        if selection:
            self._show_instance_detail(selection[0])

    def _show_instance_detail(self, iid: str) -> None:
        instance = self.instance_by_key.get(iid)
        if instance is None:
            return
        lines = [
            f"名称：{instance.name}",
            f"启动器：{instance.launcher}",
            f"游戏目录：{instance.game_dir}",
            f"options.txt：{instance.options_path}",
            f"MC 版本：{instance.mc_version or '未知'}    加载器：{instance.loader or '未知'}",
            f"状态：{'有 options.txt' if instance.exists else '尚未启动过'}",
        ]
        if instance.default_targets:
            lines.append("附加默认值文件：")
            lines.extend(f"    {p}" for p in instance.default_targets)
        if instance.has_optifine:
            lines.append(f"OptiFine：{instance.optifine_path}")
        messagebox.showinfo("实例详情", "\n".join(lines), parent=self)

    # ------------------------------------------------------------------
    # 后台任务
    # ------------------------------------------------------------------
    def run_bg(self, work, done=None, busy_text: str = "处理中…") -> None:
        """在后台线程里跑 ``work(progress)``，结果回主线程交给 ``done``。"""
        self.set_status(busy_text, busy=True)
        job_queue = self._jobs

        def progress(message: str) -> None:
            job_queue.put(("progress", message))

        def runner() -> None:
            try:
                result = work(progress)
                job_queue.put(("done", (done, result)))
            except Exception as exc:  # noqa: BLE001 - 兜底，避免线程静默死掉
                job_queue.put(("error", (exc, traceback.format_exc())))

        threading.Thread(target=runner, daemon=True).start()

    def _poll_jobs(self) -> None:
        try:
            while True:
                kind, payload = self._jobs.get_nowait()
                if kind == "progress":
                    self.set_status(str(payload), busy=True)
                elif kind == "done":
                    callback, result = payload
                    self.set_status("就绪", busy=False)
                    if callback is not None:
                        try:
                            callback(result)
                        except Exception:  # noqa: BLE001
                            self.log(traceback.format_exc(), "error")
                elif kind == "error":
                    exc, text = payload
                    self.set_status("出错", busy=False)
                    self.log(f"出错了：{exc}", "error")
                    self.log(text.strip().splitlines()[-1] if text else "", "error")
        except queue.Empty:
            pass
        self.after(60, self._poll_jobs)

    # ------------------------------------------------------------------
    # 实例
    # ------------------------------------------------------------------
    def on_scan(self) -> None:
        include_drive = messagebox.askyesno(
            "扫描范围",
            "要顺便扫描整个磁盘来找出装在自定义路径的整合包吗？\n\n"
            "· 选『是』：更全，但第一次可能要花几十秒。\n"
            "· 选『否』：只查常见启动器路径，很快。\n\n"
            "（你的 PCL2 如果装在非默认位置，选『是』才能自动找到；"
            "也可以之后用『添加目录』手动指定。）",
            parent=self)
        self._do_scan(include_drive)

    def _do_scan(self, include_drive: bool) -> None:
        def work(progress):
            instances = self.app.discover_instances(
                do_drive_scan=include_drive, progress=progress)
            if instances:
                progress("正在读取各整合包装了哪些 Mod（首次较慢，之后有缓存）……")
                self.app.ensure_mod_index(instances, progress=progress)
            return instances

        self.log("开始扫描实例……", "dim")
        self.run_bg(work, self._after_scan, "正在扫描实例……")

    def _after_scan(self, instances: list[Instance]) -> None:
        self.instances = instances
        self.instance_by_key = {i.key: i for i in instances}
        self._refresh_instance_tree()
        self._refresh_profile_combo()
        self._refresh_config_sources()
        # 启动时会在扫描之前先恢复上次的主配置，那时还没有实例、也就找不到原版
        # 语言文件，『其他设置』只能显示英文名。扫描完补刷一次。
        if self.profile is not None and not self._options_lang_ready:
            self.refresh_options()

        if not instances:
            self.log("没有发现任何实例。请用『添加目录…』手动指定 .minecraft 目录。", "warn")
        else:
            self.log(f"共发现 {len(instances)} 个实例。", "ok")
            for instance in instances:
                mark = "有 options.txt" if instance.exists else "尚未启动过"
                self.log(f"    {instance.name}  [{instance.version_label}]  {mark}", "dim")
        self.refresh_diff()

    def _refresh_instance_tree(self) -> None:
        previously = set(self.instance_tree.checked_items())
        self.instance_tree.clear()
        for instance in self.instances:
            iid = instance.key
            checked = (iid in previously) if previously else True
            if not instance.exists:
                checked = False
            self.instance_tree.add_row(iid, [
                _short(instance.name, 30),
                instance.version_label,
                self._key_count(instance),
                "就绪" if instance.exists else "未启动",
            ], checked=checked)
        self._update_instance_count()

    def _key_count(self, instance: Instance) -> str:
        """实例的按键数量（带 mtime+size 缓存，列表刷新时不必重复解析 options.txt）。"""
        path = instance.options_path
        if not path.is_file():
            return "-"
        try:
            stat = path.stat()
        except OSError:
            return "?"
        stamp = (stat.st_mtime, stat.st_size)
        cached = self._key_count_cache.get(str(path))
        if cached is not None and cached[0] == stamp:
            return cached[1]
        try:
            from mcsync.optionsfile import OptionsFile

            count = str(OptionsFile.load(path).keybind_count)
        except OSError:
            count = "?"
        self._key_count_cache[str(path)] = (stamp, count)
        return count

    def _update_instance_count(self) -> None:
        total = len(self.instances)
        chosen = len(self._selected_instances())
        try:
            self.instance_count_var.set(f"已选 {chosen} / {total}")
        except tk.TclError:
            pass

    def on_add_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 .minecraft 目录或实例根目录", parent=self)
        if not path:
            return
        directory = Path(path)
        as_instance_dir = messagebox.askyesno(
            "目录类型",
            "这是一个「每个子文件夹一个实例」的目录吗？\n\n"
            "· 是 —— 例如 Prism 的 instances 目录、CurseForge 的 Instances 目录\n"
            "· 否 —— 例如 .minecraft 目录本身（里面有 versions 文件夹）",
            parent=self)
        self.app.add_manual_dir(directory, as_instance_dir=as_instance_dir)
        self.log(f"已添加目录：{directory}", "ok")
        self._do_scan(False)

    def on_open_data(self) -> None:
        _open_in_explorer(self.app.data_dir)

    def on_open_backups(self) -> None:
        _open_in_explorer(self.app.backups_dir)

    # ------------------------------------------------------------------
    # 主配置
    # ------------------------------------------------------------------
    def _refresh_profile_combo(self) -> None:
        names = [p.name for p in self.app.load_profiles()]
        self.profile_combo["values"] = names
        if names and self.profile_var.get() not in names:
            self.profile_var.set(names[0])
            self.on_profile_selected()
        elif not names:
            self.profile_var.set("")
            self.profile = None
            self.refresh_diff()

    def on_profile_selected(self) -> None:
        name = self.profile_var.get()
        if not name:
            self.profile = None
            return
        for profile in self.app.load_profiles():
            if profile.name == name:
                self.profile = profile
                self.log(f"已载入主配置「{name}」：{profile.binding_count} 个按键"
                         f"（已绑定 {profile.bound_count()} 个）", "ok")
                break
        self.refresh_diff()
        self.refresh_options()

    def on_capture(self) -> None:
        if not self.instances:
            messagebox.showwarning("还没有实例", "请先扫描实例。", parent=self)
            return
        dialog = CaptureDialog(self, [i for i in self.instances if i.exists])
        self.wait_window(dialog)
        if not dialog.result:
            return
        instance, name = dialog.result

        def work(progress):
            progress(f"正在读取 {instance.name} 的按键……")
            return self.app.capture_profile(instance, name)

        self.run_bg(work, self._after_capture, "正在抓取键位……")

    def _after_capture(self, profile: Profile) -> None:
        self.app.save_profile(profile)
        self.log(f"已保存主配置「{profile.name}」：{profile.binding_count} 个按键", "ok")
        self._refresh_profile_combo()
        self.profile_var.set(profile.name)
        self.on_profile_selected()

    def on_save_profile(self) -> None:
        """把当前主配置落盘。

        平时抓到/改到都会自动保存，这个按钮是给「我想确认一下它真的存好了」
        以及手工改完整份键位之后用的。
        """
        if self.profile is None:
            messagebox.showwarning("没有主配置", "请先『从实例抓取…』或『导入方案』。",
                                   parent=self)
            return
        try:
            path = self.app.save_profile(self.profile)
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.log(f"已保存主配置「{self.profile.name}」"
                 f"（{self.profile.bound_count()} 个已绑定按键）→ {path}", "ok")
        self.set_status(f"已保存主配置「{self.profile.name}」")

    def on_import_profile(self) -> None:
        path = filedialog.askopenfilename(
            title="导入主配置", filetypes=[("按键配置", "*.json"), ("所有文件", "*.*")],
            parent=self)
        if not path:
            return
        try:
            profile = Profile.load(Path(path))
        except (OSError, ValueError) as exc:
            messagebox.showerror("导入失败", str(exc), parent=self)
            return
        self.app.save_profile(profile)
        self.log(f"已导入「{profile.name}」", "ok")
        self._refresh_profile_combo()
        self.profile_var.set(profile.name)
        self.on_profile_selected()

    def on_export_profile(self) -> None:
        if self.profile is None:
            messagebox.showwarning("没有主配置", "请先抓取或导入一份主配置。", parent=self)
            return
        path = filedialog.asksaveasfilename(
            title="导出主配置", defaultextension=".json",
            initialfile=f"{self.profile.name}.json",
            filetypes=[("按键配置", "*.json")], parent=self)
        if not path:
            return
        self.profile.save(Path(path))
        self.log(f"已导出到 {path}", "ok")

    def on_rename_profile(self) -> None:
        """给当前主配置改名（就是改它在 data/profiles 下的文件名）。"""
        if self.profile is None:
            messagebox.showwarning("没有主配置", "请先抓取或导入一份主配置。", parent=self)
            return
        old = self.profile.name
        new = simpledialog.askstring("重命名主配置", f"把「{old}」重命名为：",
                                     initialvalue=old, parent=self)
        if new is None:
            return
        new = new.strip()
        if not new or new == old:
            return
        if any(c in new for c in '\\/:*?"<>|'):
            messagebox.showerror(
                "名字不合法", '配置名里不能出现 \\ / : * ? " < > | 这些字符。', parent=self)
            return
        if new in {p.name for p in self.app.load_profiles() if p.name != old}:
            messagebox.showerror("名字重复", f"已经有一个叫「{new}」的配置了。", parent=self)
            return
        self.profile.rename(new)
        self.app.delete_profile(old)
        self.app.save_profile(self.profile)
        self._refresh_profile_combo()
        self.profile_var.set(new)
        self.on_profile_selected()
        self.log(f"配置「{old}」已重命名为「{new}」", "ok")

    def on_delete_profile(self) -> None:
        name = self.profile_var.get()
        if not name:
            return
        if not messagebox.askyesno("删除主配置", f"确定要删除配置「{name}」吗？", parent=self):
            return
        self.app.delete_profile(name)
        self.profile = None
        self._refresh_profile_combo()
        self.log(f"已删除配置「{name}」", "warn")

    # ------------------------------------------------------------------
    # 对比
    # ------------------------------------------------------------------
    def refresh_diff(self) -> None:
        targets = self._selected_instances()
        self.keybind_tree.set_columns(self._keybind_columns())

        if self.profile is None or not targets:
            self.keybind_tree.clear()
            self.keymap_tab.refresh()
            return

        profile = self.profile

        def work(progress):
            progress("正在对比按键……")
            self.app.ensure_mod_index(targets, progress=progress)
            return self.app.make_diff(profile, targets)

        self.run_bg(work, self._after_diff, "正在对比……")

    def _after_diff(self, table: DiffTable) -> None:
        self.diff_table = table
        self._populate_keybind_tree()
        self.keymap_tab.refresh()

    def _populate_keybind_tree(self) -> None:
        tree = self.keybind_tree
        tree.clear()
        table = self.diff_table
        if table is None or self.profile is None:
            return

        targets = self._selected_instances()
        only_diff = self.only_diff_var.get()
        resolver = self.app.resolver

        rows = sorted(table.rows, key=lambda r: resolver.sort_key(r.binding_name))
        shown = 0
        for row in rows:
            kinds = [row.kind_for(instance.key) for instance in targets]
            has_diff = any(k != ChangeKind.SAME for k in kinds)
            if only_diff and not has_diff:
                continue

            profile_text = row.profile_value.display() if row.profile_value else "-"
            values = [row.info.group, row.info.display, profile_text]
            dominant = ChangeKind.SAME
            for instance, kind in zip(targets, kinds):
                actual = row.instance_values.get(instance.key)
                if kind == ChangeKind.SAME:
                    values.append(actual.display() if actual else "-")
                elif kind == ChangeKind.ONLY_IN_PROFILE:
                    values.append("（没有此键）")
                else:
                    values.append(actual.display() if actual else "-")
                if kind != ChangeKind.SAME and dominant == ChangeKind.SAME:
                    dominant = kind

            tag = KIND_STYLE[dominant][1]
            tree.add_row(row.binding_name, values, checked=has_diff, tags=[tag])
            shown += 1

        if shown == 0:
            self.log("对比完成：所有已勾选的实例都与主配置一致。", "ok")
        else:
            self.log(f"对比完成：列出 {shown} 个按键。", "dim")
        self._apply_filter()

    def _show_keybind_detail(self) -> None:
        """『按键对比』下方详情：这一行的归属、以及它在各实例里的实际键位。"""
        selection = self.keybind_tree.tree.selection()
        if not selection or self.diff_table is None:
            self.keybind_detail.configure(text="选中一行可以看到这个功能的归属和各实例的实际键位。")
            return
        binding = selection[0]
        row = next((r for r in self.diff_table.rows if r.binding_name == binding), None)
        if row is None:
            self.keybind_detail.configure(text=binding)
            return

        info = row.info
        lines = [f"{info.display}　—　{info.binding_name}"]
        meta = []
        if info.group:
            meta.append(f"分类：{info.group}")
        if info.owner_name:
            meta.append(f"归属：{info.owner_name}")
        if info.semantic_action:
            meta.append(f"同功能分组：{info.semantic_action}")
        if meta:
            lines.append("　|　".join(meta))
        lines.append(f"主配置：{row.profile_value.display() if row.profile_value else '未绑定'}")
        for instance in self._selected_instances():
            kind = row.kind_for(instance.key)
            value = row.instance_values.get(instance.key)
            if kind == ChangeKind.ONLY_IN_PROFILE:
                text = "（这个实例没有这个按键）"
            else:
                text = value.display() if value else "未绑定"
            lines.append(f"{instance.name}：{text}　[{KIND_STYLE[kind][0]}]")
        self.keybind_detail.configure(text="\n".join(lines))

    def _apply_filter(self) -> None:
        needle = (self.filter_var.get() or "").strip().lower()
        tree = self.keybind_tree
        # 被筛掉的行是用 tree.detach() 藏起来的，它们不在 get_children() 里，
        # 所以必须按 all_items() 遍历，否则清空关键词后这些行永远回不来。
        for iid in tree.all_items():
            if not needle:
                tree.tree.reattach(iid, "", "end")
                continue
            values = " ".join(str(v) for v in tree.tree.item(iid, "values")).lower()
            if needle in values:
                tree.tree.reattach(iid, "", "end")
            else:
                tree.tree.detach(iid)

    def _on_keybind_toggle(self, _iid: str, _checked: bool) -> None:
        pass

    def _select_diff_rows(self, checked: bool) -> None:
        tree = self.keybind_tree
        targets = self._selected_instances()
        table = self.diff_table
        for iid in tree.all_items():
            should = checked
            if checked and table is not None:
                row = next((r for r in table.rows if r.binding_name == iid), None)
                if row is not None:
                    should = any(row.kind_for(i.key) != ChangeKind.SAME for i in targets)
            tree.set_checked(iid, should)

    # ------------------------------------------------------------------
    # 其他设置
    # ------------------------------------------------------------------
    def refresh_options(self) -> None:
        for child in self.options_container.inner.winfo_children():
            child.destroy()
        self.selected_options.clear()
        self._update_options_note()
        if self.profile is None:
            return

        names = sorted(self.profile.options)
        if not names:
            ttk.Label(self.options_container.inner,
                      text="这份主配置没有抓取其他设置。重新抓取时请勾选「包含其他设置」。",
                      style="Hint.TLabel").pack(anchor="w", padx=6, pady=6)
            return

        recommended = set(DEFAULT_SYNCED_OPTIONS)
        # 用户上次勾过的就以那次为准；一次都没同步过（设置里是空的）就按推荐来。
        saved = set(self.app.settings.option_names)
        lang = self.app.vanilla_lang(self.instances) if self.instances else None
        self._options_lang_ready = bool(lang)
        if self.instances and not lang:
            self.log("没找到原版中文语言文件，设置项只能用英文名显示。", "dim")
        for name in names:
            if saved:
                checked = name in saved
            else:
                checked = (name in recommended
                           or name.startswith("soundCategory_"))
            var = tk.BooleanVar(value=checked)
            self.selected_options[name] = var
            row = ttk.Frame(self.options_container.inner)
            row.pack(fill="x", anchor="w", padx=6, pady=1)
            zh, raw = lang.option_display(name) if lang else (name, "")
            ttk.Checkbutton(row, text=zh, variable=var, width=24,
                            style=mcstyle.check_style(ttk.Style(self), mcstyle.GREEN)
                            ).pack(side="left")
            if raw:
                ttk.Label(row, text=raw, width=26, style="Dim.TLabel",
                          font=self.fonts["small"]).pack(side="left")
            ttk.Label(row, text=self.profile.options[name], width=16,
                      style="Hint.TLabel").pack(side="left")
            note = "推荐" if name in recommended else (
                "实例相关，通常不该同步" if name in INSTANCE_SPECIFIC_OPTIONS else "")
            if note:
                ttk.Label(row, text=note, style="Hint.TLabel").pack(side="left")

        # 默认把「推荐」的那些勾上：不然这一页打开全是空的，
        # 用户直接点「同步其他设置」会什么都不做，看起来就像同步没生效。
        if not saved:
            self._select_safe_options()
        chosen = len(self._collect_option_choices())
        self.log(f"『其他设置』里列出了 {len(names)} 项，当前勾选 {chosen} 项，"
                 "可以自己加减。", "dim")

    def _select_options(self, checked: bool) -> None:
        for var in self.selected_options.values():
            var.set(checked)

    def _update_options_note(self) -> None:
        """提示「本页勾选的东西会不会被顶栏的一键同步带上」。"""
        if not hasattr(self, "options_note_label"):
            return
        if self.app.settings.sync_options:
            self.options_note_label.configure(
                text="顶栏的「一键同步」会连本页勾选的设置一起同步。", style="Hint.TLabel")
            self.options_note_button.pack_forget()
        else:
            self.options_note_label.configure(
                text="顶栏的「一键同步」默认只同步按键，本页勾选的设置不会跟着走。"
                     "想让它们一起同步，点下面的按钮"
                     "（等于打开『同步选项』页里的「同时同步其他设置」）：",
                style="Warn.TLabel")
            self.options_note_button.pack(anchor="w", pady=(3, 0))

    def on_enable_options_in_all(self) -> None:
        self.app.settings.sync_options = True
        self.app.save_settings()
        var = self.policy_vars.get("sync_options")
        if var is not None:
            var.set(True)
        self._update_options_note()
        self.log("已打开「同时同步其他设置」：以后点顶栏的「一键同步」"
                 "会连本页勾选的设置一起同步。", "ok")

    def _select_safe_options(self) -> None:
        for name, var in self.selected_options.items():
            var.set(name in DEFAULT_SYNCED_OPTIONS or name.startswith("soundCategory_"))

    def _collect_option_choices(self) -> list[str]:
        return [name for name, var in self.selected_options.items() if var.get()]

    # ------------------------------------------------------------------
    # 模组配置文件
    # ------------------------------------------------------------------
    def _refresh_config_sources(self) -> None:
        values = [i.name for i in self.instances]
        self.config_source_combo["values"] = values
        if values and self.config_source_var.get() not in values:
            source = self._guess_source_instance()
            self.config_source_var.set(source.name if source else values[0])

    def _guess_source_instance(self) -> Instance | None:
        if self.profile and self.profile.source:
            for instance in self.instances:
                if str(instance.game_dir) == self.profile.source:
                    return instance
        chosen = self._selected_instances()
        return chosen[0] if chosen else (self.instances[0] if self.instances else None)

    def on_scan_configs(self) -> None:
        instance = self._config_source_instance()
        if instance is None:
            messagebox.showwarning("没有源实例", "请先扫描实例。", parent=self)
            return

        def work(progress):
            progress(f"正在扫描 {instance.name} 的配置文件……")
            return self.app.scan_config_files(instance)

        self.run_bg(work, self._after_scan_configs, "正在扫描配置文件……")

    def _after_scan_configs(self, candidates: list) -> None:
        self.config_candidates = candidates
        self.config_tree.clear()
        for index, candidate in enumerate(candidates):
            fields = "、".join(candidate.key_fields[:3])
            self.config_tree.add_row(f"c{index}", [
                candidate.relative_path,
                fields or "-",
            ], checked=False)
        if not candidates:
            self.log("没有发现含快捷键的独立配置文件。"
                     "（这很正常——绝大多数模组的按键都在 options.txt 里）", "dim")
        else:
            self.log(f"发现 {len(candidates)} 个疑似含快捷键的配置文件。", "ok")

    def on_sync_configs(self) -> None:
        source = self._config_source_instance()
        if source is None:
            return
        chosen = [self.config_candidates[int(iid[1:])]
                  for iid in self.config_tree.checked_items()
                  if iid.startswith("c") and int(iid[1:]) < len(self.config_candidates)]
        if not chosen:
            messagebox.showinfo("没有选中文件", "请先勾选要同步的配置文件。", parent=self)
            return
        targets = [i for i in self._selected_instances() if i.key != source.key]
        if not targets:
            messagebox.showinfo("没有目标", "请在左侧勾选至少一个目标实例。", parent=self)
            return
        if not messagebox.askyesno(
                "确认", f"把 {len(chosen)} 个文件从「{source.name}」"
                        f"复制到 {len(targets)} 个实例？\n\n覆盖前会自动备份。", parent=self):
            return
        paths = [c.relative_path for c in chosen]

        def work(progress):
            progress("正在复制配置文件……")
            return self.app.sync_config_files(source, targets, paths)

        self.run_bg(work, self._after_sync_configs, "正在复制……")

    def _after_sync_configs(self, results: list) -> None:
        ok = sum(1 for r in results if r.ok)
        for result in results:
            if result.ok:
                self.log(f"✓ {result.source} -> {result.target}", "ok")
            else:
                self.log(f"✗ {result.source} -> {result.target}：{result.error}", "error")
        if ok:
            self.log(f"配置文件同步完成：{ok}/{len(results)} 成功。", "ok")

    def _config_source_instance(self) -> Instance | None:
        name = self.config_source_var.get()
        for instance in self.instances:
            if instance.name == name:
                return instance
        return None

    # ------------------------------------------------------------------
    # 备份
    # ------------------------------------------------------------------
    def refresh_backups(self) -> None:
        records = self.app.backup_manager.list()
        self.backup_tree.clear()
        for index, record in enumerate(records):
            size = _dir_size(record.directory)
            self.backup_tree.add_row(f"b{index}", [
                record.created,
                _short(record.label, 26),
                str(record.file_count),
                _human_size(size),
            ], checked=False)
        self.log(f"共 {len(records)} 份备份。", "dim")

    def on_restore_backup(self) -> None:
        selection = self.backup_tree.tree.selection()
        if not selection:
            messagebox.showinfo("没有选中", "请在列表里选中要还原的备份。", parent=self)
            return
        records = self.app.backup_manager.list()
        chosen = [records[int(iid[1:])] for iid in selection if int(iid[1:]) < len(records)]
        if not chosen:
            return
        # 备份目录名是 yyyymmdd-HHMMSS，按它排就是时间序；多选时从旧到新依次写回，
        # 最后一份生效——这样「Shift 连选一段」的结果是可预期的。
        chosen.sort(key=lambda r: r.directory.name)
        listing = "\n".join(f"  · {r.title}" for r in chosen)
        extra = ("\n\n你选了多份，会按时间从旧到新依次写回，**最后一份**是最终结果。"
                 if len(chosen) > 1 else "")
        if not messagebox.askyesno(
                "确认还原",
                f"要把这 {len(chosen)} 份备份写回原路径吗？\n\n{listing}{extra}\n\n"
                "当前文件会先被自动备份一份，所以这一步可以再来一次。", parent=self):
            return
        for record in chosen:
            restored, errors = self.app.backup_manager.restore(record)
            self.log(f"已还原「{record.title}」，{restored} 个文件。", "ok")
            for error in errors:
                self.log(f"  ✗ {error}", "error")
        self.refresh_backups()
        self.refresh_diff()

    def on_delete_backup(self) -> None:
        selection = self.backup_tree.tree.selection()
        if not selection:
            return
        records = self.app.backup_manager.list()
        chosen = [records[int(iid[1:])] for iid in selection if int(iid[1:]) < len(records)]
        if not chosen:
            return
        if len(chosen) == 1:
            question = f"删除「{chosen[0].title}」？"
        else:
            question = f"删除这 {len(chosen)} 份备份？\n\n" + "\n".join(
                f"  · {r.title}" for r in chosen)
        if messagebox.askyesno("删除备份", question, parent=self):
            for record in chosen:
                self.app.backup_manager.delete(record)
            self.refresh_backups()

    # ------------------------------------------------------------------
    # 同步
    # ------------------------------------------------------------------
    def _collect_policy(self) -> None:
        info = self.app.settings
        for key, var in self.policy_vars.items():
            setattr(info, key, bool(var.get()))
        info.option_names = self._collect_option_choices()
        self.app.save_settings()

    def on_preview(self) -> None:
        self._request_plan(self._print_plan)

    def on_reset_state(self) -> None:
        """清空同步基线。"""
        if not messagebox.askyesno(
                "重置同步基线",
                "确定要忘掉全部「上次同步时的键位」记录吗？\n\n"
                "之后第一次同步会按主配置强制对齐，包括你手动解绑过的键。",
                parent=self):
            return
        self.app.reset_sync_state()
        self.log("同步基线已重置。", "ok")

    def on_sync(self) -> None:
        """全局同步：按键 + 你在『同步选项』里打开的全部内容。"""
        self._request_plan(self._confirm_and_apply, scope=SCOPE_ALL)

    def on_sync_keybinds(self) -> None:
        """只同步按键（不动其他设置），供「键位图」页使用。"""
        self._request_plan(self._confirm_and_apply, scope=SCOPE_KEYBINDS)

    def on_sync_options(self) -> None:
        """只同步「其他设置」里勾选的项。"""
        self._collect_policy()
        if not self.app.settings.option_names:
            messagebox.showwarning(
                "没有勾选设置",
                "『其他设置』页里一个都没勾选，这次同步等于什么都不做。\n\n"
                "可以点「仅危险项以外全选」按推荐勾上，或直接改勾选。",
                parent=self)
            return
        self._request_plan(self._confirm_and_apply, scope=SCOPE_OPTIONS)

    def on_sync_selected_keybinds(self) -> None:
        """只同步『按键对比』里勾选的那些按键。"""
        rows = self.keybind_tree.checked_items()
        if not rows:
            messagebox.showwarning("没有选中按键",
                                   "请先在列表里勾选要同步的按键。", parent=self)
            return
        self._request_plan(self._confirm_and_apply, scope=SCOPE_KEYBINDS,
                           bindings=set(rows))

    def _scoped_policy(self, scope: str) -> SyncPolicy:
        """按本次同步范围微调策略。

        只影响这一次的计划，不回写设置——否则「只同步其他设置」会把
        『同步选项』里的勾选永久改掉，下次全局同步就少做了事。
        """
        policy = self.app.make_policy()
        if scope == SCOPE_KEYBINDS:
            return replace(policy, sync_options=False)
        if scope == SCOPE_OPTIONS:
            return replace(policy, sync_keybinds=False, sync_options=True,
                           option_names=set(self._collect_option_choices()))
        return policy

    def _request_plan(self, then, scope: str = SCOPE_ALL,
                      bindings: set[str] | None = None) -> None:
        """校验前置条件，然后在后台生成同步计划，完成后回主线程调用 ``then``。

        ``scope`` 决定本次只同步哪一部分；``bindings`` 用来覆盖「按勾选行同步」。
        """
        if self.profile is None:
            messagebox.showwarning("没有主配置", "请先抓取或导入一份主配置。", parent=self)
            return
        targets = self._selected_instances()
        if not targets:
            messagebox.showwarning("没有目标", "请在左侧勾选要同步的实例。", parent=self)
            return
        if self._busy:
            self.log("上一个任务还没做完，请稍等。", "warn")
            return

        self._collect_policy()
        policy = self._scoped_policy(scope)
        if (scope == SCOPE_ALL and not policy.sync_options
                and self.app.settings.option_names):
            self.log(f"提示：『其他设置』里已勾选 "
                     f"{len(self.app.settings.option_names)} 项，但『同步选项』里的"
                     "「同时同步其他设置」没打开，本次只同步按键。", "warn")
        if bindings is None:
            bindings = set(self.keybind_tree.checked_items())
        elif scope == SCOPE_KEYBINDS:
            # 页内「同步选中按键」：把这次要动的绑定名也反映到勾选状态上，
            # 后面的确认对话框和变更预览才不会给人一种「没勾也改了」的感觉。
            self.keybind_tree.set_all_checked(False)
            for name in bindings:
                if self.keybind_tree.row(name) is not None:
                    self.keybind_tree.set_checked(name, True)
        selected = {instance.key: set(bindings) for instance in targets}
        profile = self.profile
        scope_text = {"all": "全部", "keybinds": "按键",
                      "options": "其他设置"}.get(scope, "全部")

        def work(progress):
            progress("正在生成同步计划……")
            self.app.ensure_mod_index(targets, progress=progress)
            return self.app.make_plan(profile, targets, selected=selected,
                                      progress=progress, policy=policy)

        def done(plan):
            self.last_plan = plan
            then(plan)

        self.run_bg(work, done, f"正在生成{scope_text}同步计划……")

    def _print_plan(self, plan: SyncPlan) -> None:
        if plan.total_changes == 0:
            self.log("所有已勾选实例都已经和主配置一致，无需改动。", "ok")
            return
        self.log(f"同步计划：{plan.target_count} 个文件需要改动。", "ok")
        for inst_plan in plan.plans:
            if not inst_plan.has_changes:
                continue
            self.log(f"  ● {inst_plan.instance_name} —— {inst_plan.summary()}")
            for change in inst_plan.keybind_changes[:8]:
                self.log(f"      {change.display}：{change.old.display()} -> "
                         f"{change.new.display()}"
                         + (f"   ({change.note})" if change.note else ""), "dim")
            if len(inst_plan.keybind_changes) > 8:
                self.log(f"      …… 还有 {len(inst_plan.keybind_changes) - 8} 个按键", "dim")
            for change in inst_plan.option_changes[:5]:
                self.log(f"      [设置] {change.describe()}", "dim")
            for item in inst_plan.skipped[:3]:
                self.log(f"      [跳过] {item.display}：{item.reason}", "warn")
        conflicts = plan.all_conflicts()
        if conflicts:
            self.log(f"⚠ 同步后会有 {len(conflicts)} 处按键冲突：", "warn")
            for instance_name, conflict in conflicts[:8]:
                self.log(f"      [{instance_name}] {conflict.describe()}", "warn")

    def _confirm_and_apply(self, plan: SyncPlan) -> None:
        if plan.total_changes == 0:
            messagebox.showinfo("无需同步", "所有已勾选实例都已经和主配置一致。", parent=self)
            return

        conflicts = plan.all_conflicts()
        summary = [f"将修改 {plan.target_count} 个文件，共 {plan.total_changes} 处变更。", ""]
        for inst_plan in plan.plans:
            if inst_plan.has_changes:
                summary.append(f"· {inst_plan.instance_name}：{inst_plan.summary()}")
        if conflicts:
            summary += ["", f"⚠ 同步后会有 {len(conflicts)} 处按键冲突（同一个键绑给多个功能）。"]
        summary += ["", "写入前会自动备份。请确认 Minecraft 已经完全退出。"]

        if not messagebox.askyesno("确认同步", "\n".join(summary), parent=self):
            return

        def work(progress):
            progress("正在备份并写入……")
            return self.app.run_plan(plan, do_backup=True, progress=progress)

        self.run_bg(work, self._after_sync, "正在写入……")

    def _after_sync(self, results: list) -> None:
        ok = 0
        for result in results:
            if result.ok:
                ok += 1
                self.log(f"✓ {result.instance_name}：写入 {result.written_keybinds} 个按键、"
                         f"{result.written_options} 项设置", "ok")
                if result.backup:
                    self.log(f"    备份：{result.backup}", "dim")
            else:
                self.log(f"✗ {result.instance_name}：{result.error}", "error")
        if results:
            self.log(f"同步完成：{ok}/{len(results)} 个文件成功。", "ok" if ok == len(results) else "warn")
        self.refresh_backups()
        self.refresh_diff()

    # ------------------------------------------------------------------
    def report_callback_exception(self, exc_type, value, tb) -> None:  # noqa: N802
        """Tk 回调里抛异常时不要静默失败——记日志并弹窗。"""
        text = "".join(traceback.format_exception(exc_type, value, tb))
        try:
            self.log(f"出错了：{value}", "error")
        except Exception:  # noqa: BLE001 - 连日志都写不了就只弹窗
            pass
        messagebox.showerror("运行出错", text, parent=self)

    def _on_close(self) -> None:
        try:
            self._collect_policy()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._save_ui()          # 记住窗口尺寸、分栏位置、上次看的标签页
        except Exception:  # noqa: BLE001
            pass
        self.destroy()


# ----------------------------------------------------------------------
# 对话框
# ----------------------------------------------------------------------

class CaptureDialog(tk.Toplevel):
    """选择「从哪个实例抓取主配置」。"""

    def __init__(self, parent: SyncApp, instances: list[Instance]) -> None:
        super().__init__(parent)
        self.title("从实例抓取主配置")
        self.result: tuple[Instance, str] | None = None
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="选择要抓取键位的实例：").grid(row=0, column=0, sticky="w")
        self.combo = ttk.Combobox(frame, state="readonly", width=44,
                                  values=[i.name for i in instances])
        self.combo.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        if instances:
            self.combo.current(0)

        ttk.Label(frame, text="新配置的名字：").grid(row=2, column=0, sticky="w")
        self.name_var = tk.StringVar(value="我的键位")
        entry = ttk.Entry(frame, textvariable=self.name_var, width=44)
        entry.grid(row=3, column=0, sticky="ew", pady=(4, 10))

        ttk.Label(frame,
                  text="抓取会同时记下该实例的视野、GUI 缩放、音量等其他设置，\n"
                       "但同步时是否使用它们由你在『其他设置』标签页决定。",
                  style="Hint.TLabel", justify="left").grid(row=4, column=0, sticky="w")

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="抓取", command=self._ok).pack(side="right")

        frame.columnconfigure(0, weight=1)
        self.instances = instances
        entry.focus_set()
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        _center(self, parent)

    def _ok(self) -> None:
        index = self.combo.current()
        if index < 0 or index >= len(self.instances):
            return
        name = self.name_var.get().strip() or "我的键位"
        self.result = (self.instances[index], name)
        self.destroy()


# ----------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------

def _short(text: str, width: int = 40) -> str:
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size} B"


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except OSError:
        pass
    return total


def _center(window: tk.Toplevel, parent: tk.Misc) -> None:
    window.update_idletasks()
    try:
        x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 3
        window.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    except tk.TclError:
        pass


def _open_in_explorer(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            import os
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(path)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    argparse_data_dir = None
    if argv:
        for index, token in enumerate(argv):
            if token == "--data-dir" and index + 1 < len(argv):
                argparse_data_dir = Path(argv[index + 1])
    app = App(data_dir=argparse_data_dir)
    try:
        window = SyncApp(app)
    except tk.TclError as exc:
        print(f"无法启动图形界面：{exc}", file=sys.stderr)
        print("请改用命令行：python cli.py --help", file=sys.stderr)
        return 1
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
