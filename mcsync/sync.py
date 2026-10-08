# -*- coding: utf-8 -*-
"""同步执行：生成计划、备份、写入、校验。

**写入策略**（每一条都对应调研里发现的一个坑）：

1. **只写目标实例已经认识的按键**（默认）。Minecraft 退出时会整份重写
   ``options.txt``，并且「只保存自己有的值」，写进去的未知按键会被静默删除。
   这条规则直接决定了工具必须先把目标文件读出来、按绑定名逐个比对。
2. **绝不整文件替换**，只按条目 merge（借鉴 ``Configured Defaults``）。
3. **写前备份 + 写后回读校验**，任何一步不对就报告而不是假装成功。
4. **检测游戏是否在运行**：正在运行时写入会被游戏退出时覆盖掉。
5. **跨大版本转换**：目标实例若还在用 1.12 的数字键码，自动转换；
   转换不了的（如修饰键组合）跳过并明确告知，绝不写猜测值。
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .backups import BackupManager, BackupRecord
from .diff import BindingDiff, DiffTable, Conflict, find_conflicts
from .keycodes import KeyCombo, UNBOUND, is_valid_combo
from .legacy_codes import convert_value
from .naming import NamingResolver
from .optionsfile import INSTANCE_SPECIFIC_OPTIONS, OptionsFile
from .profile import Profile
from .state import SyncState

ProgressFn = Callable[[str], None]


# --------------------------------------------------------------------------
# 策略
# --------------------------------------------------------------------------

@dataclass
class SyncPolicy:
    """一次同步的可选项。"""

    sync_keybinds: bool = True
    #: 目标没有这个绑定名时也写进去。默认关闭——除非目标确实装了那个 mod
    #: 并且已经启动过一次，否则写了也会被 Minecraft 抹掉。
    include_unknown_keybinds: bool = False

    sync_options: bool = False
    option_names: set[str] = field(default_factory=set)

    #: 同时写入该实例的「默认值」文件（configureddefaults / defaultoptions / kubejs），
    #: 这样整合包更新重置设置、或以后新建同类实例时，仍然是你的键位。
    write_default_targets: bool = False

    #: 允许「同功能不同 Mod」的跨 Mod 对齐（Xaero 世界地图 <-> JourneyMap 全屏地图）
    semantic_sync: bool = True

    #: 目标实例是 1.12 等旧版时自动做键码转换
    convert_legacy: bool = True

    #: 同时同步 OptiFine 的 ``optionsof.txt``（它里面也有按键，且是旧式数字键码）
    sync_optifine: bool = False

    #: 不把目标实例里已经绑好的键改成「未绑定」
    skip_unbind: bool = True

    #: 尊重「上次同步之后被手动改过」的按键。
    #: 例如你在某个整合包里把截图键解绑了，再同步时不该被主配置绑回去。
    #: 靠 ``mcsync.state.SyncState`` 里的基线快照来判断，详见那个模块的说明。
    respect_manual_changes: bool = True

    #: 目标文件不存在时是否创建（例如实例从没启动过）
    create_missing: bool = False


# --------------------------------------------------------------------------
# 计划
# --------------------------------------------------------------------------

@dataclass
class KeybindChange:
    binding_name: str
    display: str
    old: KeyCombo
    new: KeyCombo
    note: str = ""

    def describe(self) -> str:
        return f"{self.display}：{self.old.display()} -> {self.new.display()}"


@dataclass
class OptionChange:
    name: str
    old: str | None
    new: str

    def describe(self) -> str:
        old = "(不存在)" if self.old is None else self.old
        return f"{self.name}：{old} -> {self.new}"


@dataclass
class SkippedItem:
    binding_name: str
    display: str
    reason: str


@dataclass
class InstancePlan:
    """针对一个目标文件的完整变更计划。"""

    instance_name: str
    instance_key: str
    game_dir: Path
    target_path: Path
    kind: str = "options"          # options / default / config
    options: OptionsFile | None = None
    code_style: str = "named"

    keybind_changes: list[KeybindChange] = field(default_factory=list)
    option_changes: list[OptionChange] = field(default_factory=list)
    skipped: list[SkippedItem] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    #: 同步之后该实例的完整按键状态，用于冲突检测与预览
    planned_keybinds: dict[str, KeyCombo] = field(default_factory=dict)

    @property
    def total_changes(self) -> int:
        return len(self.keybind_changes) + len(self.option_changes)

    @property
    def has_changes(self) -> bool:
        return self.total_changes > 0

    def summary(self) -> str:
        if not self.has_changes:
            return "无需改动"
        parts = []
        if self.keybind_changes:
            parts.append(f"{len(self.keybind_changes)} 个按键")
        if self.option_changes:
            parts.append(f"{len(self.option_changes)} 项设置")
        return "同步 " + "、".join(parts)


@dataclass
class SyncPlan:
    """一次「一键同步」的完整计划。"""

    profile: Profile
    plans: list[InstancePlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return sum(p.total_changes for p in self.plans)

    @property
    def target_count(self) -> int:
        return sum(1 for p in self.plans if p.has_changes)

    def all_conflicts(self) -> list[tuple[str, Conflict]]:
        out: list[tuple[str, Conflict]] = []
        for plan in self.plans:
            for conflict in plan.conflicts:
                out.append((plan.instance_name, conflict))
        return out


@dataclass
class ApplyResult:
    instance_name: str
    path: Path
    ok: bool
    written_keybinds: int = 0
    written_options: int = 0
    backup: Path | None = None
    error: str = ""
    verify_note: str = ""


# --------------------------------------------------------------------------
# 生成计划
# --------------------------------------------------------------------------

def build_plan(profile: Profile,
               instances: Sequence,
               policy: SyncPolicy | None = None,
               diffs: DiffTable | None = None,
               selected: Mapping[str, set[str]] | None = None,
               resolver: NamingResolver | None = None,
               progress: ProgressFn | None = None,
               cancel: Callable[[], bool] | None = None,
               state: SyncState | None = None) -> SyncPlan:
    """生成同步计划（只读，不写盘）。

    ``selected`` 是 ``{实例 key: {绑定名, ...}}``，来自界面上勾选的行；
    传 ``None`` 表示全部可同步项都同步。
    ``state`` 是上次同步留下的基线快照，用来跳过「用户自己改过」的按键。
    """
    policy = policy or SyncPolicy()
    plan = SyncPlan(profile=profile)

    # 按实例归并全局对比表里的行，得到「每个实例该改哪些绑定」
    rows_by_instance: dict[str, list[BindingDiff]] = {}
    if diffs is not None:
        for row in diffs.rows:
            for inst_key in row.instance_values:
                rows_by_instance.setdefault(inst_key, []).append(row)

    for instance in instances:
        if cancel is not None and cancel():
            break
        if progress is not None:
            progress(f"生成计划：{instance.name}")

        targets: list[tuple[Path, str]] = []
        if instance.exists or policy.create_missing:
            targets.append((instance.options_path, "options"))
        if policy.sync_optifine and instance.has_optifine:
            targets.append((instance.optifine_path, "optifine"))
        if policy.write_default_targets:
            for extra in instance.default_targets:
                targets.append((extra, "default"))

        for target_path, kind in targets:
            inst_plan = _plan_one(
                profile, instance, target_path, kind, policy,
                rows_by_instance.get(instance.key, []),
                selected.get(instance.key) if selected is not None else None,
                resolver, diffs, state,
            )
            if inst_plan is not None:
                plan.plans.append(inst_plan)

    if not profile.keybinds:
        plan.warnings.append("主配置里没有任何按键，无法同步。")

    return plan


def _plan_one(profile: Profile,
              instance,
              target_path: Path,
              kind: str,
              policy: SyncPolicy,
              rows: list[BindingDiff],
              selected: set[str] | None,
              resolver: NamingResolver | None,
              diffs: DiffTable | None,
              state: SyncState | None = None) -> InstancePlan | None:
    if not target_path.is_file() and not policy.create_missing:
        if kind == "options":
            return None
        return None

    options = OptionsFile.load(target_path)
    code_style = options.code_style()
    plan = InstancePlan(
        instance_name=instance.name,
        instance_key=instance.key,
        game_dir=instance.game_dir,
        target_path=target_path,
        kind=kind,
        options=options,
        code_style=code_style,
    )

    # 不含 ``key_`` 前缀的 fragment（Default Options 的 keybindings.txt）可以新增条目
    is_fragment = kind == "default" and target_path.name.lower() != "options.txt"

    current = options.keybinds()
    planned = dict(current)

    legacy_target = code_style == "legacy"
    if legacy_target and not policy.convert_legacy:
        plan.warnings.append("目标实例使用旧版数字键码，已按设置跳过转换，按键不会同步。")
        plan.conflicts = []
        return plan

    # 决定每个绑定名要写成什么
    pending: list[tuple[str, KeyCombo, str]] = []   # (绑定名, 新值, 来源说明)

    if policy.sync_keybinds:
        source_rows = rows if rows else _rows_from_profile(profile, instance.key)
        for row in source_rows:
            # 目标实例上没有这个绑定名，且不是片段文件 -> 默认跳过
            exists_here = row.binding_name in current
            if not exists_here and not (policy.include_unknown_keybinds or is_fragment):
                if selected is not None and row.binding_name in selected:
                    plan.skipped.append(SkippedItem(
                        binding_name=row.binding_name,
                        display=row.info.display,
                        reason="目标实例没有这个按键（可能没装对应 Mod）",
                    ))
                continue

            if selected is not None and row.binding_name not in selected:
                continue

            if row.profile_value is None:
                continue
            if not row.profile_value.bound and policy.skip_unbind:
                continue

            # 上次同步之后被手动改过（例如在游戏里把截图键解绑了）-> 保留现状
            if (policy.respect_manual_changes and state is not None
                    and kind == "options"):
                was = current.get(row.binding_name)
                if state.manually_changed(instance.key, row.binding_name,
                                          was.to_options() if was else None):
                    plan.skipped.append(SkippedItem(
                        binding_name=row.binding_name,
                        display=row.info.display,
                        reason="上次同步后这个键被改动过（例如你在游戏里解绑/改键），"
                               "已保留你的设置",
                    ))
                    continue

            pending.append((row.binding_name, row.profile_value, row.mapped_from or ""))

    # 逐个套用（含旧版键码转换）
    for binding_name, combo, mapped_from in pending:
        value = combo.to_options()
        note = ""
        if legacy_target:
            converted, warn = convert_value(value, "legacy")
            if converted is None:
                plan.skipped.append(SkippedItem(
                    binding_name=binding_name,
                    display=resolver.display(binding_name, instance.key) if resolver else binding_name,
                    reason=warn or "无法转换为旧版键码",
                ))
                continue
            value = converted
            note = "已转换为 1.12 键码"
        elif code_style == "named" and _looks_legacy(options.get(binding_name)):
            converted, warn = convert_value(options.get(binding_name) or "", "named")
            if converted is None:
                plan.skipped.append(SkippedItem(
                    binding_name=binding_name,
                    display=resolver.display(binding_name, instance.key) if resolver else binding_name,
                    reason=warn or "无法转换旧版键码",
                ))
                continue

        new_combo = KeyCombo.parse(value)
        # 写之前先自查：Minecraft 的 InputConstants.getKey() 遇到不认识的字符串会
        # 直接抛异常，所以非法值宁可跳过也不能写进去。
        if not is_valid_combo(new_combo):
            plan.skipped.append(SkippedItem(
                binding_name=binding_name,
                display=(resolver.display(binding_name, instance.key) if resolver else binding_name),
                reason=f"键值「{new_combo.to_options()}」不是 Minecraft 认识的写法",
            ))
            continue
        old_combo = current.get(binding_name, KeyCombo())
        if old_combo == new_combo:
            planned[binding_name] = new_combo
            continue
        if mapped_from:
            note = (note + " " if note else "") + "跨 Mod 同功能对齐"
        plan.keybind_changes.append(KeybindChange(
            binding_name=binding_name,
            display=(resolver.display(binding_name, instance.key) if resolver else binding_name),
            old=old_combo,
            new=new_combo,
            note=note.strip(),
        ))
        planned[binding_name] = new_combo

    # 其他设置
    if policy.sync_options and profile.options:
        current_options = options.non_key_options()
        for name in sorted(policy.option_names):
            if name in INSTANCE_SPECIFIC_OPTIONS:
                continue
            if name not in profile.options:
                continue
            new_value = profile.options[name]
            old_value = current_options.get(name)
            if old_value == new_value:
                continue
            plan.option_changes.append(OptionChange(name=name, old=old_value, new=new_value))

    plan.planned_keybinds = planned
    plan.conflicts = find_conflicts(planned, resolver, instance.key)

    # 目标文件本身有问题时给出提示
    if options.has_bom:
        plan.warnings.append("目标文件带 UTF-8 BOM，Minecraft 可能因此重置设置（本工具写回时会去掉）。")
    if not options.trailing_newline:
        plan.warnings.append("目标文件末尾没有换行，已自动补齐。")

    return plan


def _looks_legacy(value: str | None) -> bool:
    if not value:
        return False
    head = value.split(":", 1)[0].strip()
    return bool(head) and head.lstrip("-").isdigit()


def _rows_from_profile(profile: Profile, instance_key: str) -> list[BindingDiff]:
    """没有对比表时，直接用主配置构造行。"""
    from .diff import BindingDiff as _BD
    from .naming import BindingInfo
    rows: list[_BD] = []
    for name, combo in sorted(profile.keybinds.items()):
        tk = name[4:] if name.startswith("key_") else name
        rows.append(_BD(
            binding_name=name,
            info=BindingInfo(binding_name=name, translation_key=tk, display=tk,
                             owner_mod=None, owner_name="", group="未分类",
                             is_vanilla=False, semantic_action=None),
            profile_value=combo,
            instance_values={instance_key: None},
        ))
    return rows


# --------------------------------------------------------------------------
# 执行
# --------------------------------------------------------------------------

def is_game_running(game_dirs: Sequence[Path] | None = None) -> bool | None:
    """检测 Minecraft 是否正在运行。

    返回 ``True`` / ``False``；**无法检测时返回 ``None``**（调用方应当据此提示用户
    自行确认，而不是当成「没在运行」）。
    """
    commands: list[list[str]] = []
    if sys.platform == "win32":
        commands.append(["tasklist", "/FI", "IMAGENAME eq javaw.exe", "/FO", "CSV", "/NH"])
        commands.append(["tasklist", "/FI", "IMAGENAME eq java.exe", "/FO", "CSV", "/NH"])

    found_any_java = False
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return None
        out = (proc.stdout or "").lower()
        if "javaw.exe" in out or "java.exe" in out:
            found_any_java = True

    if not found_any_java:
        return False

    # 有 java 进程，尽量进一步确认是不是 Minecraft
    ok, lines = _java_command_lines()
    if not ok:
        return True   # 有 java 但拿不到命令行，保守认为可能在跑
    needles = ["minecraft", "net.minecraft", "fabric", "forge", "bootstraplauncher",
               "cpw.mods", "minecraft-launcher"]
    if game_dirs:
        needles += [str(p).lower() for p in game_dirs]
    for line in lines:
        low = line.lower()
        if any(n in low for n in needles):
            return True
    return False


def _java_command_lines() -> tuple[bool, list[str]]:
    """尽力拿到 java 进程的命令行。拿不到时返回 ``(False, [])``。"""
    if sys.platform != "win32":
        return False, []
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
           "Get-CimInstance Win32_Process -Filter \"Name like '%java%'\" "
           "| Select-Object -ExpandProperty CommandLine"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False, []
    if proc.returncode != 0:
        return False, []
    return True, [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]


def apply_plan(plan: SyncPlan,
               backup_manager: BackupManager | None = None,
               do_backup: bool = True,
               force: bool = False,
               progress: ProgressFn | None = None,
               state: SyncState | None = None) -> list[ApplyResult]:
    """执行计划。``force=True`` 时即使检测到游戏在运行也继续。

    ``state`` 传进来时，写完之后会把各实例 ``options.txt`` 里**真实**的键位
    重新采集一遍存成新基线，供下次同步判断「哪些键是用户自己改过的」。
    """
    results: list[ApplyResult] = []

    # 1) 游戏运行检测（只看真正要改的实例）
    real_plans = [p for p in plan.plans if p.has_changes and p.kind == "options"]
    if real_plans and not force:
        game_dirs = sorted({p.game_dir for p in real_plans})
        running = is_game_running(game_dirs)
        if running is True:
            for p in plan.plans:
                results.append(ApplyResult(
                    instance_name=p.instance_name, path=p.target_path, ok=False,
                    error="检测到 Minecraft 正在运行。请先完全退出游戏，"
                          "否则退出时会把刚写入的按键覆盖掉。",
                ))
            return results

    # 2) 备份
    backup_record: BackupRecord | None = None
    if do_backup and backup_manager is not None:
        files = [(p.target_path, p.instance_name, p.kind)
                 for p in plan.plans if p.has_changes]
        if progress is not None:
            progress(f"备份 {len(files)} 个文件……")
        backup_record = backup_manager.create(
            files, label="同步前",
            note=f"配置：{plan.profile.name}；目标 {plan.target_count} 个实例")

    # 3) 写入
    for inst_plan in plan.plans:
        if not inst_plan.has_changes:
            continue
        if progress is not None:
            progress(f"写入：{inst_plan.instance_name}")
        results.append(_apply_one(inst_plan, backup_record))

    # 4) 采集新基线（连同一点改动都没有的实例一起，这样第一次同步就能
    #    把当前状态记下来，之后用户在游戏里的改动才有个「参照物」）
    if state is not None:
        _record_baseline(plan, state)

    return results


def _record_baseline(plan: SyncPlan, state: SyncState) -> None:
    """把每个目标实例 ``options.txt`` 里真实的键位存成新基线。"""
    for inst_plan in plan.plans:
        if inst_plan.kind != "options":
            continue
        try:
            fresh = OptionsFile.load(inst_plan.target_path)
        except OSError:
            continue
        keybinds = fresh.keybinds()
        if not keybinds:
            continue
        state.record(inst_plan.instance_key,
                     {name: combo.to_options()
                      for name, combo in keybinds.items()})
    state.save()


def _apply_one(inst_plan: InstancePlan,
               backup_record: BackupRecord | None) -> ApplyResult:
    result = ApplyResult(instance_name=inst_plan.instance_name,
                         path=inst_plan.target_path, ok=False)
    if backup_record is not None:
        result.backup = backup_record.directory

    options = inst_plan.options
    if options is None:
        result.error = "内部错误：没有载入目标文件"
        return result

    # 先改内存表示
    for change in inst_plan.keybind_changes:
        options.set(change.binding_name, change.new.to_options())
    for change in inst_plan.option_changes:
        options.set(change.name, change.new)

    # 写回：始终 UTF-8、去掉 BOM、沿用原换行符
    options.has_bom = False
    try:
        options.save()
    except OSError as exc:
        result.error = f"写入失败：{exc}"
        return result

    # 回读校验：确认真的写进去了，而不是「以为写进去了」
    try:
        verify = OptionsFile.load(inst_plan.target_path)
    except OSError as exc:
        result.error = f"写入后无法回读校验：{exc}"
        return result

    actual = verify.keybinds()
    mismatched: list[str] = []
    for change in inst_plan.keybind_changes:
        if actual.get(change.binding_name) != change.new:
            mismatched.append(change.binding_name)
    if mismatched:
        result.error = f"回读校验失败，以下按键没有写入成功：{', '.join(mismatched[:5])}"
        return result

    verify_options = verify.non_key_options()
    for change in inst_plan.option_changes:
        if verify_options.get(change.name) != change.new:
            result.error = f"回读校验失败：设置项 {change.name} 未生效"
            return result

    result.ok = True
    result.written_keybinds = len(inst_plan.keybind_changes)
    result.written_options = len(inst_plan.option_changes)
    if verify.has_bom:
        result.verify_note = "注意：回读发现文件仍带 BOM"
    return result
