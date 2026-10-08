# -*- coding: utf-8 -*-
"""MCKeyBinder 按键同步器 —— 命令行入口。

用法示例::

    python cli.py list                       # 列出发现的实例
    python cli.py inspect 1                  # 看某个实例的按键清单
    python cli.py capture 1 -n 我的键位        # 把实例 1 的键位存成主配置
    python cli.py diff 我的键位               # 打印差异对比表
    python cli.py sync 我的键位 --all -y      # 一键同步到所有实例
    python cli.py backups                    # 列出备份
    python cli.py restore 1                  # 还原最近一次备份
    python cli.py selftest                   # 用合成数据自测

加 ``--json`` 可以把结果导出成 JSON，方便脚本处理。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接 `python cli.py` 运行
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcsync import APP_NAME, __version__
from mcsync.app import App
from mcsync.diff import CHANGE_META, ChangeKind
from mcsync.optionsfile import OptionsFile


# --------------------------------------------------------------------------
# 输出小工具
# --------------------------------------------------------------------------

def out(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))


def pick_instances(app: App, selectors: list[str]) -> list:
    """按序号或名字片段挑实例。"""
    if not selectors:
        return []
    chosen = []
    for selector in selectors:
        if selector.isdigit():
            index = int(selector) - 1
            if 0 <= index < len(app.instances):
                chosen.append(app.instances[index])
            continue
        lowered = selector.lower()
        for instance in app.instances:
            if lowered in instance.name.lower() or lowered in str(instance.game_dir).lower():
                chosen.append(instance)
    # 去重且保序
    seen = set()
    unique = []
    for instance in chosen:
        if instance.key not in seen:
            seen.add(instance.key)
            unique.append(instance)
    return unique


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def cmd_list(app: App, args) -> int:
    progress = (lambda m: out(f"  · {m}")) if args.verbose else None
    app.discover_instances(do_drive_scan=not args.no_scan, progress=progress)
    if not app.instances:
        out("没有发现任何 Minecraft 实例。用 `add <目录>` 手动指定一个。")
        return 1

    if args.json:
        out(json.dumps([{
            "index": i + 1, "name": inst.name, "launcher": inst.launcher,
            "game_dir": str(inst.game_dir), "options": str(inst.options_path),
            "mc_version": inst.mc_version, "loader": inst.loader,
            "exists": inst.exists,
            "default_targets": [str(p) for p in inst.default_targets],
        } for i, inst in enumerate(app.instances)], ensure_ascii=False, indent=2))
        return 0

    out(f"\n发现 {len(app.instances)} 个实例：\n")
    out(f"{'#':>3}  {'名称':<34} {'版本':<18} {'启动器':<12} 状态")
    out("-" * 92)
    for i, inst in enumerate(app.instances, 1):
        status = "有 options.txt" if inst.exists else "未启动过"
        out(f"{i:>3}  {_cut(inst.name, 34):<34} {_cut(inst.version_label, 18):<18} "
            f"{_cut(inst.launcher, 12):<12} {status}")
    out()
    return 0


def cmd_inspect(app: App, args) -> int:
    app.discover_instances(do_drive_scan=False)
    instances = pick_instances(app, args.targets)
    if not instances:
        out("没有匹配的实例。先运行 `list` 看看序号。")
        return 1
    app.ensure_mod_index(instances)

    for instance in instances:
        if not instance.options_path.is_file():
            out(f"\n=== {instance.name}：还没有 options.txt ===")
            continue
        options = OptionsFile.load(instance.options_path)
        keybinds = options.keybinds()
        out(f"\n=== {instance.name}  ({instance.version_label}) ===")
        out(f"    目录：{instance.game_dir}")
        out(f"    按键：{len(keybinds)} 个   键码风格：{options.code_style()}")
        if args.keys:
            for name in sorted(keybinds, key=lambda n: app.resolver.sort_key(n, instance.key)):
                info = app.resolver.resolve(name, instance.key)
                out(f"      {keybinds[name].display():<18} {info.display:<30} "
                    f"[{info.group}]  {name}")
    return 0


def cmd_capture(app: App, args) -> int:
    app.discover_instances(do_drive_scan=False)
    instances = pick_instances(app, [args.source])
    if not instances:
        out("找不到源实例。")
        return 1
    instance = instances[0]
    name = args.name or instance.name
    profile = app.capture_profile(instance, name)
    path = app.save_profile(profile)
    out(f"已从「{instance.name}」抓取 {profile.binding_count} 个按键"
        f"（其中已绑定 {profile.bound_count()} 个）")
    out(f"保存到：{path}")
    return 0


def cmd_diff(app: App, args) -> int:
    app.discover_instances(do_drive_scan=False)
    profile = _load_profile(app, args.profile)
    if profile is None:
        return 1
    targets = pick_instances(app, args.targets) or app.instances
    if not targets:
        out("没有可比对的实例。")
        return 1
    app.ensure_mod_index(targets)

    table = app.make_diff(profile, targets)
    out(f"\n主配置「{profile.name}」有 {profile.binding_count} 个按键，"
        f"比对 {len(targets)} 个实例：\n")

    header = f"{'按键':<28}" + "".join(f"{_cut(t.name, 16):<18}" for t in targets)
    out(header)
    out("-" * (28 + 18 * len(targets)))

    shown = 0
    for row in sorted(table.rows, key=lambda r: app.resolver.sort_key(r.binding_name)):
        kinds = [row.kind_for(t.key) for t in targets]
        if all(k == ChangeKind.SAME for k in kinds):
            continue
        shown += 1
        if args.limit and shown > args.limit:
            continue
        line = f"{_cut(row.info.display, 28):<28}"
        for kind in kinds:
            line += f"{_cut(CHANGE_META[kind][0], 16):<18}"
        out(line)

    if shown == 0:
        out("（全部一致，没有差异）")
    elif args.limit and shown > args.limit:
        out(f"\n…… 还有 {shown - args.limit} 行，用 --limit 调整。")

    summary = table.summary()
    out("\n统计：" + "、".join(
        f"{CHANGE_META[ChangeKind(k)][0]} {v}" for k, v in sorted(summary.items())))
    return 0


def cmd_sync(app: App, args) -> int:
    app.discover_instances(do_drive_scan=False)
    profile = _load_profile(app, args.profile)
    if profile is None:
        return 1
    targets = pick_instances(app, args.targets) or app.instances
    if not targets:
        out("没有可同步的实例。")
        return 1

    app.settings.semantic_sync = not args.no_semantic
    app.settings.include_unknown_keybinds = args.include_unknown
    app.settings.sync_options = args.with_options
    if args.with_options and not app.settings.option_names:
        app.settings.option_names = list(profile.options)
    app.settings.write_default_targets = args.defaults
    if args.force_align:
        # 默认保留你同步之后手动改过的按键，这个开关强制每次都对齐主配置。
        app.settings.respect_manual_changes = False
        app.save_settings()

    app.ensure_mod_index(targets)
    out(f"正在为 {len(targets)} 个实例生成同步计划……")
    plan = app.make_plan(profile, targets)

    if plan.total_changes == 0:
        out("所有实例都已经和主配置一致，无需改动。")
        return 0

    out()
    for inst_plan in plan.plans:
        if not inst_plan.has_changes:
            continue
        out(f"● {inst_plan.instance_name}  —— {inst_plan.summary()}")
        out(f"    {inst_plan.target_path}")
        for change in inst_plan.keybind_changes[:12]:
            out(f"      {change.display:<28} {change.old.display():<16} -> "
                f"{change.new.display()}" + (f"   ({change.note})" if change.note else ""))
        if len(inst_plan.keybind_changes) > 12:
            out(f"      …… 还有 {len(inst_plan.keybind_changes) - 12} 个按键")
        for change in inst_plan.option_changes[:8]:
            out(f"      [设置] {change.describe()}")
        for item in inst_plan.skipped[:5]:
            out(f"      [跳过] {item.display}：{item.reason}")
        if inst_plan.skipped and len(inst_plan.skipped) > 5:
            out(f"      [跳过] …… 还有 {len(inst_plan.skipped) - 5} 项")
        out()

    conflicts = plan.all_conflicts()
    if conflicts:
        out(f"⚠ 同步后会出现 {len(conflicts)} 处按键冲突：")
        for instance_name, conflict in conflicts[:10]:
            out(f"    [{instance_name}] {conflict.describe()}")
        out()

    if not args.yes:
        if not _confirm("确认写入这些文件吗？"):
            out("已取消。")
            return 1

    results = app.run_plan(plan, do_backup=not args.no_backup, force=args.force)
    out()
    ok = 0
    for result in results:
        mark = "✓" if result.ok else "✗"
        out(f"{mark} {result.instance_name}  ({result.path})")
        if result.ok:
            ok += 1
            out(f"    已写入 {result.written_keybinds} 个按键、"
                f"{result.written_options} 项设置")
            if result.backup:
                out(f"    备份：{result.backup}")
        else:
            out(f"    {result.error}")
    out(f"\n完成：{ok}/{len(results)} 个文件写入成功。")
    return 0 if ok == len(results) else 1


def cmd_backups(app: App, args) -> int:
    records = app.backup_manager.list()
    if not records:
        out("还没有任何备份。")
        return 0
    out(f"\n共 {len(records)} 份备份（合计 "
        f"{app.backup_manager.total_size() / 1024:.0f} KB）：\n")
    for i, record in enumerate(records, 1):
        out(f"{i:>3}  {record.title}   {record.file_count} 个文件")
        if args.verbose:
            for entry in record.entries:
                out(f"        {entry.source}")
    out()
    return 0


def cmd_restore(app: App, args) -> int:
    records = app.backup_manager.list()
    if not records:
        out("没有可还原的备份。")
        return 1
    index = int(args.backup) - 1 if args.backup else 0
    if not (0 <= index < len(records)):
        out("备份序号超出范围。")
        return 1
    record = records[index]
    out(f"准备还原：{record.title}（{record.file_count} 个文件）")
    for entry in record.entries:
        out(f"    -> {entry.source}")
    if not args.yes and not _confirm("确认还原吗？当前文件会先自动备份一份。"):
        out("已取消。")
        return 1
    restored, errors = app.backup_manager.restore(record)
    out(f"\n已还原 {restored} 个文件。")
    for error in errors:
        out(f"  ✗ {error}")
    return 0 if not errors else 1


def cmd_add(app: App, args) -> int:
    path = Path(args.path).expanduser()
    if not path.is_dir():
        out(f"目录不存在：{path}")
        return 1
    app.add_manual_dir(path, as_instance_dir=args.instances_dir)
    out(f"已添加：{path}")
    app.discover_instances(do_drive_scan=False, progress=lambda m: out(f"  · {m}"))
    out(f"现在共有 {len(app.instances)} 个实例。")
    return 0


def cmd_selftest(app: App, args) -> int:
    from tests.selftest import run_selftest
    return run_selftest(verbose=args.verbose,
                        work_dir=Path(args.work_dir) if args.work_dir else None)


# --------------------------------------------------------------------------
# 辅助
# --------------------------------------------------------------------------

def _cut(text: str, width: int) -> str:
    """按显示宽度粗略截断（中文按两格算）。"""
    out_chars = []
    used = 0
    for ch in text:
        w = 2 if ord(ch) > 0x2E80 else 1
        if used + w > width:
            break
        out_chars.append(ch)
        used += w
    return "".join(out_chars)


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes", "是")


def _load_profile(app: App, selector: str | None) -> Profile | None:
    if selector:
        path = Path(selector)
        if path.is_file():
            try:
                return Profile.load(path)
            except (OSError, ValueError) as exc:
                out(f"读取配置失败：{exc}")
                return None
        for profile in app.load_profiles():
            if profile.name == selector:
                return profile
        out(f"找不到名为「{selector}」的配置。")
        return None
    profiles = app.load_profiles()
    if not profiles:
        out("还没有任何配置。先用 `capture <实例序号>` 抓一份。")
        return None
    return profiles[0]


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcsync", description=f"{APP_NAME} v{__version__} —— "
        "免装 Mod 的 Minecraft 跨整合包按键同步器")
    parser.add_argument("--data-dir", help="数据目录（默认在程序旁边的 data/）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="列出发现的实例")
    p.add_argument("--no-scan", action="store_true", help="跳过磁盘扫描（更快）")
    p.add_argument("--json", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("inspect", help="查看实例的按键")
    p.add_argument("targets", nargs="*")
    p.add_argument("--keys", action="store_true", help="列出每一个按键")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("capture", help="从实例抓取一份主配置")
    p.add_argument("source", help="实例序号或名称")
    p.add_argument("-n", "--name", help="配置名")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("diff", help="对比主配置与各实例")
    p.add_argument("profile", nargs="?", help="配置名或 JSON 路径")
    p.add_argument("targets", nargs="*", help="实例序号，省略则全部")
    p.add_argument("--limit", type=int, default=60)
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("sync", help="把主配置同步到实例")
    p.add_argument("profile", nargs="?", help="配置名或 JSON 路径")
    p.add_argument("targets", nargs="*", help="实例序号，省略则全部")
    p.add_argument("-y", "--yes", action="store_true", help="不再询问")
    p.add_argument("--force", action="store_true", help="检测到游戏在运行也继续")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--no-semantic", action="store_true", help="关闭跨 Mod 同功能对齐")
    p.add_argument("--include-unknown", action="store_true",
                   help="目标没有的按键也写入（有风险，可能被游戏抹掉）")
    p.add_argument("--with-options", action="store_true", help="同时同步其他设置")
    p.add_argument("--defaults", action="store_true",
                   help="同时写入 configureddefaults / defaultoptions 等默认值文件")
    p.add_argument("--force-align", action="store_true",
                   help="连你同步之后手动解绑/改过的按键也强制改回主配置的值")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("backups", help="列出备份")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_backups)

    p = sub.add_parser("restore", help="还原备份")
    p.add_argument("backup", nargs="?", help="备份序号，默认最近一份")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("add", help="手动添加实例目录")
    p.add_argument("path")
    p.add_argument("--instances-dir", action="store_true",
                   help="按「一个子目录一个实例」解析（Prism/CurseForge 风格）")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("selftest", help="用合成数据自测（不会碰真实实例）")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--work-dir", help="自测用的临时工作目录")
    p.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    app = App(Path(args.data_dir) if args.data_dir else None)
    try:
        return args.func(app, args)
    except KeyboardInterrupt:
        out("\n已中断。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
