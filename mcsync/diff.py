# -*- coding: utf-8 -*-
"""差异对比与冲突检测。

两件事：

**对比（diff）** —— 把「主配置」和若干实例放在一起横向比较，生成一张差异表，
让用户在写盘之前先看清楚哪个整合包的哪个键跟主配置不一致。

**冲突检测（conflict）** —— 同一个实例里，同步之后是否会出现「一个键被绑两次」。
调研结论是：``AutoKeyBinds`` / ``Controlling`` 已经做了冲突检测，所以它不该是
本工具的主线功能，但作为**同步前的提醒**很有价值（否则要进游戏才发现）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence

from .keycodes import KeyCombo
from .naming import BindingInfo, NamingResolver

#: 冲突检测时要忽略的键（未绑定本身不算冲突）
_IGNORED_CODES = frozenset({"key.keyboard.unknown", ""})


class ChangeKind(str, Enum):
    SAME = "same"                 # 主配置与实例一致
    DIFFERS = "differs"           # 两边都绑了，但不一样
    TARGET_UNBOUND = "unbound"    # 实例里是「未绑定」，主配置有值
    PROFILE_UNBOUND = "profile_unbound"   # 主配置里是「未绑定」，实例有值
    ONLY_IN_TARGET = "only_target"        # 只有实例有，主配置没有这个绑定名
    ONLY_IN_PROFILE = "only_profile"      # 只有主配置有（该实例没这个 mod）
    SEMANTIC = "semantic"         # 靠「同功能不同 mod」映射上的


#: 界面里每种状态的中文说明与建议是否默认勾选
CHANGE_META: dict[ChangeKind, tuple[str, bool]] = {
    ChangeKind.SAME: ("一致", False),
    ChangeKind.DIFFERS: ("不一致", True),
    ChangeKind.TARGET_UNBOUND: ("目标未绑定", True),
    ChangeKind.PROFILE_UNBOUND: ("将被设为未绑定", False),
    ChangeKind.ONLY_IN_TARGET: ("仅目标有", False),
    ChangeKind.ONLY_IN_PROFILE: ("目标没有此按键", False),
    ChangeKind.SEMANTIC: ("同功能按键（跨 Mod）", True),
}


@dataclass
class BindingDiff:
    """一个绑定名在所有被比较对象上的取值。"""

    binding_name: str
    info: BindingInfo
    profile_value: KeyCombo | None = None
    #: 实例 key -> 该实例上的值（``None`` 表示该实例没有这个绑定名）
    instance_values: dict[str, KeyCombo | None] = field(default_factory=dict)
    #: 主配置里的绑定名（可能与 ``binding_name`` 不同，走语义映射时）
    mapped_from: str | None = None

    def kind_for(self, instance_key: str) -> ChangeKind:
        target = self.instance_values.get(instance_key)
        if target is None:
            return ChangeKind.ONLY_IN_PROFILE if self.profile_value is not None \
                else ChangeKind.SAME
        if self.profile_value is None:
            return ChangeKind.SAME
        if target == self.profile_value:
            return ChangeKind.SAME
        if self.mapped_from is not None:
            return ChangeKind.SEMANTIC
        if not target.bound:
            return ChangeKind.TARGET_UNBOUND
        if not self.profile_value.bound:
            return ChangeKind.PROFILE_UNBOUND
        return ChangeKind.DIFFERS

    @property
    def has_any_difference(self) -> bool:
        return any(self.kind_for(k) != ChangeKind.SAME
                   for k in self.instance_values)


@dataclass
class DiffTable:
    """完整的对比结果。"""

    rows: list[BindingDiff] = field(default_factory=list)
    #: 实例 key -> 展示名
    instance_labels: dict[str, str] = field(default_factory=dict)
    #: 被比较的实例顺序
    instance_keys: list[str] = field(default_factory=list)

    def differences(self) -> list[BindingDiff]:
        return [r for r in self.rows if r.has_any_difference]

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in self.rows:
            for key in self.instance_keys:
                kind = row.kind_for(key)
                out[kind.value] = out.get(kind.value, 0) + 1
        return out


# --------------------------------------------------------------------------
# 构建对比表
# --------------------------------------------------------------------------

def build_diff(profile_keybinds: Mapping[str, KeyCombo],
               instances: Sequence,
               keybinds_by_instance: Mapping[str, Mapping[str, KeyCombo]],
               resolver: NamingResolver | None = None,
               semantic_sync: bool = False,
               semantic_grouper=None,
               name_resolver_instance: str | None = None) -> DiffTable:
    """构建对比表。

    ``semantic_sync=True`` 时，除了名字精确匹配，还会尝试「同功能不同 mod」的映射：
    例如主配置里的 ``key_gui.xaero_open_map`` 会去匹配目标实例里的
    ``key_key.journeymap.fullscreen``。
    """
    resolver_key = name_resolver_instance or (instances[0].key if instances else "")
    table = DiffTable(instance_keys=[i.key for i in instances])
    table.instance_labels = {i.key: i.name for i in instances}

    # ---- 1) 名字精确匹配的绑定 ----
    all_names: set[str] = set(profile_keybinds)
    for kb in keybinds_by_instance.values():
        all_names |= set(kb)

    for name in sorted(all_names):
        info = (resolver.resolve(name, resolver_key) if resolver else
                _placeholder_info(name))
        row = BindingDiff(
            binding_name=name,
            info=info,
            profile_value=profile_keybinds.get(name),
            instance_values={
                inst_key: kb.get(name)
                for inst_key, kb in keybinds_by_instance.items()
            },
        )
        table.rows.append(row)

    # ---- 2) 语义匹配（同功能不同 mod）----
    if semantic_sync and semantic_grouper is not None:
        _add_semantic_rows(table, profile_keybinds, keybinds_by_instance,
                           resolver, semantic_grouper, resolver_key)

    return table


def _add_semantic_rows(table: DiffTable,
                       profile_keybinds: Mapping[str, KeyCombo],
                       keybinds_by_instance: Mapping[str, Mapping[str, KeyCombo]],
                       resolver: NamingResolver | None,
                       grouper,
                       resolver_key: str) -> None:
    """给「主配置有 A、目标实例只有等价的 B」这种情况补行。"""
    existing = {row.binding_name for row in table.rows}

    for binding_name, combo in profile_keybinds.items():
        translation_key = binding_name[4:] if binding_name.startswith("key_") else binding_name
        action = grouper.action_of(translation_key)
        if action is None:
            continue

        for inst_key, kb in keybinds_by_instance.items():
            if binding_name in kb:
                continue  # 精确匹配已经覆盖
            # 在该实例里找同一语义动作、且它确实拥有的绑定
            for peer in grouper.candidates(action):
                peer_binding = "key_" + peer
                if peer_binding in kb and peer_binding not in existing:
                    info = (resolver.resolve(peer_binding, inst_key) if resolver
                            else _placeholder_info(peer_binding))
                    row = BindingDiff(
                        binding_name=peer_binding,
                        info=info,
                        profile_value=combo,
                        mapped_from=binding_name,
                        instance_values={
                            k: v.get(peer_binding) for k, v in keybinds_by_instance.items()
                        },
                    )
                    table.rows.append(row)
                    existing.add(peer_binding)


def _placeholder_info(binding_name: str) -> BindingInfo:
    tk = binding_name[4:] if binding_name.startswith("key_") else binding_name
    return BindingInfo(
        binding_name=binding_name,
        translation_key=tk,
        display=tk,
        owner_mod=None,
        owner_name="",
        group="未分类",
        is_vanilla=False,
        semantic_action=None,
    )


# --------------------------------------------------------------------------
# 冲突检测
# --------------------------------------------------------------------------

@dataclass
class Conflict:
    """一个键被绑定了多次。"""

    combo: KeyCombo
    entries: list[tuple[str, str]]   # (绑定名, 显示名)

    @property
    def combo_display(self) -> str:
        return self.combo.display()

    def describe(self) -> str:
        names = "、".join(display for _, display in self.entries)
        return f"{self.combo_display} 被同时绑定给：{names}"


def find_conflicts(keybinds: Mapping[str, KeyCombo],
                   resolver: NamingResolver | None = None,
                   instance_key: str = "",
                   limit: int = 60) -> list[Conflict]:
    """找出 ``keybinds`` 里被重复绑定的键。

    鼠标键与未绑定项不参与，与 ``AutoKeyBinds`` 的保护策略一致。
    """
    buckets: dict[str, list[str]] = {}
    for name, combo in keybinds.items():
        if not combo.bound:
            continue
        if combo.code in _IGNORED_CODES:
            continue
        buckets.setdefault(combo.to_options(), []).append(name)

    out: list[Conflict] = []
    for combo_key, names in buckets.items():
        if len(names) < 2:
            continue
        combo = KeyCombo.parse(combo_key)
        entries = []
        for name in names[:8]:
            display = (resolver.display(name, instance_key) if resolver else name)
            entries.append((name, display))
        out.append(Conflict(combo=combo, entries=entries))
        if len(out) >= limit:
            break

    out.sort(key=lambda c: (-len(c.entries), c.combo_display))
    return out


def conflicts_from_plan(planned: Mapping[str, KeyCombo],
                        resolver: NamingResolver | None = None,
                        instance_key: str = "") -> list[Conflict]:
    """对「同步之后的目标状态」做冲突检测。"""
    return find_conflicts(planned, resolver, instance_key)
