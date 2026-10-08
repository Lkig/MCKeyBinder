# -*- coding: utf-8 -*-
"""GUI 冒烟测试：把界面真的建起来、灌入合成数据、走一遍主要流程。

不做视觉断言（那需要人工看），只保证：

* 窗口能成功创建（控件层级、列定义、样式都没写错）
* 实例列表、对比表、设置项、备份列表都能正常填充
* 后台任务 + 事件循环能正常跑完，不会卡死或抛异常

运行：``python tests/gui_smoke.py``
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcsync.app import App
from mcsync.keymap_model import STATE_ORDER
from gui import widgets

FAILURES: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        print(f"  ✓ {label}")
    else:
        FAILURES.append(label + (f" —— {detail}" if detail else ""))
        print(f"  ✗ {label}" + (f" —— {detail}" if detail else ""))


def pump(window, seconds: float = 1.0, until=None) -> None:
    """跑事件循环，直到条件满足或超时。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        window.update()
        if until is not None and until():
            return
        time.sleep(0.02)


def main() -> int:
    work = Path(__file__).resolve().parent.parent / "data" / ".guismoke"
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    from tests.selftest import build_fixture
    paths = build_fixture(work / "fixture")

    print("GUI 冒烟测试")
    print("=" * 60)

    try:
        import tkinter as tk
    except ImportError as exc:
        print(f"跳过：本机没有 tkinter（{exc}）")
        return 0

    from gui.app import SyncApp

    app = App(data_dir=work / "data")
    try:
        window = SyncApp(app, autostart=False)
    except tk.TclError as exc:
        print(f"跳过：无法创建窗口（{exc}）—— 通常是当前环境没有桌面会话")
        return 0

    window.withdraw()   # 不弹到屏幕前面
    window.update()
    check(True, "主窗口创建成功")
    check(window.notebook.index("end") == 6, "6 个标签页都建好了",
          f"实际 {window.notebook.index('end')}")
    check(window.instance_tree is not None, "实例列表控件存在")
    check(window.keybind_tree is not None, "对比表控件存在")
    check(window.backup_tree is not None, "备份表控件存在")
    check(window.keymap_tab is not None and window.keymap_tab.keymap is not None,
          "键位图标签页存在")
    tabs = [window.notebook.tab(i, "text") for i in range(window.notebook.index("end"))]
    check("键位图" in tabs, "键位图是其中一个标签页", f"实际 {tabs}")

    # ---- 灌入合成实例 ----
    from mcsync.instances import scan_game_dir
    instances = scan_game_dir(paths["mc"], "PCL2")
    check(len(instances) >= 5, "合成实例被创建", f"实际 {len(instances)}")

    app.instances = instances
    window._after_scan(instances)
    window.update()
    rows = window.instance_tree.tree.get_children()
    check(len(rows) == len(instances), "实例列表填充完成",
          f"{len(rows)} vs {len(instances)}")
    check(window.instance_tree.is_checked(instances[0].key)
          or not instances[0].exists,
          "有 options.txt 的实例默认被勾选")

    # 勾上全部（有些实例默认未勾选）
    window._set_all_instances(True)
    window.update()

    # ---- 抓取主配置 ----
    by_name = {i.name: i for i in instances}
    profile = app.capture_profile(by_name["PackA-Alpha"], "冒烟测试配置")
    app.save_profile(profile)
    window._refresh_profile_combo()
    window.profile_var.set(profile.name)
    window.on_profile_selected()
    check(window.profile is not None, "主配置已载入界面")
    check(window.profile_var.get() == profile.name, "下拉框显示配置名")

    # ---- 对比（异步）----
    window.refresh_diff()
    pump(window, 30.0, until=lambda: window.diff_table is not None)
    check(window.diff_table is not None, "对比表生成完成（后台线程 + 事件循环正常）")

    row_count = len(window.diff_tree_rows()) if hasattr(window, "diff_tree_rows") \
        else len(window.keybind_tree.tree.get_children())
    check(row_count > 0, "对比表里有行", f"实际 {row_count}")

    columns = window.keybind_tree.column_ids
    check(len(columns) >= 4 + 1, "对比表按选中实例动态加了列", f"实际 {columns}")
    check(any(c.startswith("i_") for c in columns), "实例列命名正确")

    # ---- 只看差异 / 筛选 ----
    # 筛选是靠 tree.detach() 做的，被藏起来的行既不在 get_children() 里，
    # 也不该从 checked_items() 里消失（否则一键同步会静默漏掉它们）。
    all_iids = list(window.keybind_tree.all_items())
    checked_before = set(window.keybind_tree.checked_items())
    window.filter_var.set("潜行")
    window.update()
    visible = len(window.keybind_tree.tree.get_children())
    check(visible < len(all_iids), "筛选真的藏起了行",
          f"藏了 {len(all_iids) - visible} / {len(all_iids)}")
    check(set(window.keybind_tree.checked_items()) == checked_before,
          "筛掉的行不会从「勾选项」里消失")
    window.filter_var.set("")
    window.update()
    check(len(window.keybind_tree.tree.get_children()) == len(all_iids),
          "清空关键词后所有行都回来了",
          f"实际 {len(window.keybind_tree.tree.get_children())} / {len(all_iids)}")

    # ---- 键位图页 ----
    keymap = window.keymap_tab
    check(len(keymap.usages) > 0, "键位图算出了键位占用", f"实际 {len(keymap.usages)}")
    check(keymap.view_combo["values"][0].startswith("主配置"),
          "视角下拉框第一项是主配置", f"实际 {keymap.view_combo['values']}")
    check(len(keymap.view_combo["values"]) >= 2, "视角下拉框列出了实例")
    check(keymap.keymap.states != {}, "键盘控件收到了状态")

    occupied = sorted(keymap.usages)
    keymap._on_select(occupied[0])
    window.update()
    check(keymap.selected_code == occupied[0], "点键后详情面板记住了选中的键")
    check(len(keymap.detail_body.winfo_children()) > 0, "详情面板渲染出了内容")

    keymap.keyword_var.set("潜行")
    window.update()
    check(len(keymap.usages) <= len(occupied), "关键词过滤生效",
          f"{len(keymap.usages)} vs {len(occupied)}")
    keymap.keyword_var.set("")
    window.update()

    keymap._quick_states({"conflict"})
    window.update()
    check(True, "「仅冲突」快捷过滤不报错")
    keymap._quick_states(set(STATE_ORDER))
    window.update()

    # 切到实例视角应当是只读的
    keymap.view_var.set(keymap.view_combo["values"][1])
    keymap._recompute()
    window.update()
    check(keymap._current_view_key() is not None, "能切到实例视角")
    keymap.view_var.set(keymap.view_combo["values"][0])
    keymap._recompute()
    window.update()
    check(keymap._current_view_key() is None, "能切回主配置视角")

    # 就地改键：直接走提交路径（弹窗那层由 ask_key 负责，这里只验写入与刷新）
    if window.profile is not None:
        from mcsync.keycodes import KeyCombo, UNBOUND

        names = [r.binding_name for r in (window.diff_table.rows if window.diff_table else [])
                 if r.profile_value is not None and r.profile_value.code != UNBOUND]
        check(bool(names), "对比表里有已绑定的按键可以改",
              f"实际 {len(names)} 个候选")
        if names:
            target = names[0]
            before = window.profile.get(target)
            new_combo = KeyCombo.parse("key.keyboard.f24")
            keymap._commit_edit(target, new_combo, "改键（冒烟测试）")
            window.update()
            check(window.profile.get(target) == new_combo,
                  "改键后主配置内存里的值变了",
                  f"改前 {before} 改后 {window.profile.get(target)}")
            on_disk = {p.name: p for p in app.load_profiles()}
            saved = on_disk.get(window.profile.name)
            check(saved is not None and saved.get(target) == new_combo,
                  "改键后主配置文件里也写进去了")
            pump(window, 3.0)
            window.update()
            check(keymap._current_view_key() is None
                  and len(keymap.usages) > 0,
                  "改键后键位图重新算过且没炸")

    # ---- 其他设置页 ----
    window.refresh_options()
    window.update()
    check(len(window.selected_options) > 0, "其他设置列表填充完成",
          f"实际 {len(window.selected_options)} 项")
    window._select_safe_options()
    window.update()
    check(any(v.get() for v in window.selected_options.values()),
          "「仅危险项以外全选」勾上了推荐项")

    # ---- 「关键设置没同步」的两处根因 ----
    # ① 以前一打开这页一个都不勾，点「同步其他设置」等于什么都不做。
    app.settings.option_names = []
    window.refresh_options()
    window.update()
    preset = window._collect_option_choices()
    check(len(preset) > 0, "第一次打开「其他设置」就默认勾上了推荐项",
          f"实际勾选 {len(preset)} / {len(window.selected_options)}")

    # ② 顶栏的「一键同步」默认不带设置，页面上要有提示和一键打开。
    app.settings.sync_options = False
    window._update_options_note()
    window.update()
    check(window.options_note_button.winfo_manager() == "pack",
          "「一键同步」不带设置时，页面上有开启按钮")
    check("默认只同步按键" in window.options_note_label.cget("text"),
          "提示文案说明了原因", window.options_note_label.cget("text"))
    window.on_enable_options_in_all()
    window.update()
    check(app.settings.sync_options is True, "一键打开后设置里的开关也打开了")
    check(window.policy_vars["sync_options"].get() is True,
          "一键打开后「同步选项」页的勾选框也跟着勾上")
    check(not window.options_note_button.winfo_manager(),
          "打开之后提示按钮消失")
    app.settings.sync_options = False
    window.policy_vars["sync_options"].set(False)
    window._update_options_note()
    window.update()

    # ---- 同步选项页 ----
    check(set(window.policy_vars) >= {
        "semantic_sync", "sync_options", "write_default_targets",
        "sync_optifine", "convert_legacy", "skip_unbind",
        "include_unknown_keybinds"}, "同步选项控件齐全")
    window._collect_policy()
    check(app.settings.semantic_sync is True, "策略被写回设置")

    # ---- 生成计划 ----
    targets = window._selected_instances()
    selected = {i.key: set(window.keybind_tree.checked_items()) for i in targets}
    plan = app.make_plan(window.profile, targets, selected=selected)
    check(plan.total_changes > 0, "从界面状态能生成同步计划",
          f"变更 {plan.total_changes}；目标 {len(targets)} 个；"
          f"对比表 {len(window.keybind_tree.tree.get_children())} 行；"
          f"勾选按键 {sum(len(v) for v in selected.values())} 个")
    window._print_plan(plan)
    window.update()
    check(True, "计划能打印进日志区")

    # ---- 备份页 ----
    # 造两份，才能真正验证「多选」（一份的话选中数永远等于 1）
    for tag, inst in (("冒烟测试 A", "PackB-Beta"), ("冒烟测试 B", "PackA-Alpha")):
        app.backup_manager.create([(by_name[inst].options_path, inst, "options")], label=tag)
    window.refresh_backups()
    window.update()
    check(len(window.backup_tree.tree.get_children()) >= 2, "备份列表填充完成")

    # 备份列表是「选择驱动」的：点中/多选之后方框必须跟着打勾，
    # 而且 Shift/Ctrl 那种一次选多行要真的能被看见。
    tree = window.backup_tree.tree
    rows = list(tree.get_children())
    tree.selection_set(rows)                 # 等价于 Ctrl+A / 全选
    window.update()
    checked = window.backup_tree.checked_items()
    check(len(checked) == len(rows) >= 2,
          f"备份列表能多选（选中 {len(rows)} 行，打勾 {len(checked)} 行）")
    glyphs = [tree.item(iid, "values")[0] for iid in rows]
    check(all(g == widgets.CHECKED for g in glyphs), "选中之后左边的方框真的打勾了")
    # 只留第一行的选择，模拟 Ctrl 挑单个
    tree.selection_set(rows[0])
    window.update()
    check(window.backup_tree.checked_items() == [rows[0]], "Ctrl 单选：只有那一行打勾")
    tree.selection_remove(*tree.selection())
    window.update()
    check(not window.backup_tree.checked_items(), "取消选择之后方框跟着取消")
    check(tree.heading("check", "text") == "", "方框那一列的表头是空的")

    # ---- 模组配置页 ----
    cfg = by_name["PackA-Alpha"].game_dir / "config" / "smoke.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('{"zoomKey": "key.keyboard.z"}', encoding="utf-8")
    window.config_source_var.set("PackA-Alpha")
    candidates = app.scan_config_files(by_name["PackA-Alpha"])
    window._after_scan_configs(candidates)
    window.update()
    check(True, "模组配置扫描流程不报错")

    # ---- 重命名主配置 ----
    from tkinter import messagebox, simpledialog

    old_name = window.profile.name
    orig_ask = simpledialog.askstring
    orig_err = messagebox.showerror
    errors: list[str] = []
    messagebox.showerror = lambda title, msg, **k: errors.append(f"{title}: {msg}")
    try:
        # 直接补丁 tkinter.simpledialog 的模块属性，gui.app 里 import 的是同一个模块
        simpledialog.askstring = lambda *a, **k: "重命名后的配置"
        window.on_rename_profile()
        window.update()

        names = {p.name for p in app.load_profiles()}
        check("重命名后的配置" in names and old_name not in names,
              "重命名换掉了磁盘上的配置文件名", f"实际 {sorted(names)}")
        check(window.profile.name == "重命名后的配置"
              and window.profile_var.get() == "重命名后的配置",
              "重命名后界面下拉框也跟着换名")

        # 非法名字要被挡下来
        simpledialog.askstring = lambda *a, **k: "带/斜杠的名字"
        window.on_rename_profile()
        check(window.profile.name == "重命名后的配置" and len(errors) == 1,
              "非法名字被拒绝，名字没变", f"errors={errors}")

        # 撞名也要被挡下来
        app.save_profile(window.profile.copy_as("重命名后的配置2"))
        simpledialog.askstring = lambda *a, **k: "重命名后的配置2"
        window.on_rename_profile()
        check(window.profile.name == "重命名后的配置" and len(errors) == 2,
              "重名被拒绝，名字没变", f"errors={errors}")

        # 取消（返回 None）什么都不做
        simpledialog.askstring = lambda *a, **k: None
        window.on_rename_profile()
        check(window.profile.name == "重命名后的配置" and len(errors) == 2,
              "取消重命名不改任何东西")
        app.delete_profile("重命名后的配置2")
        window._refresh_profile_combo()
    finally:
        simpledialog.askstring = orig_ask
        messagebox.showerror = orig_err

    # ---- 让后台任务跑干净再关 ----
    window._collect_policy()
    window.destroy()
    shutil.rmtree(work, ignore_errors=True)
    print("=" * 60)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for item in FAILURES:
            print(f"  ✗ {item}")
        return 1
    print("GUI 冒烟测试全部通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
