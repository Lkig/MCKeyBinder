# -*- coding: utf-8 -*-
"""把「按键对比表」折算成「键盘上每个键被谁占用」的模型。

这个模块刻意不依赖 tkinter：界面只是把结果画到键盘图上，而状态判定、过滤、
冲突识别都能在没有窗口的环境里跑单测。

两种视角
--------
``instance_key=None``
    **主配置视角** —— 用主配置里每个功能绑的键来铺满键盘。这回答「我要同步的
    这套键位长什么样、有没有互相打架」。
``instance_key="<实例>"``
    **实例视角** —— 用该实例``options.txt``里实际的键来铺满键盘。这回答「这个
    整合包现在是什么样、和主配置差在哪」。

状态（画在键帽上）
------------------
``free``      主配置/该实例都没用到这个键
``used``      只有一个功能占用，且各目标实例与主配置一致
``diff``      占用它的功能在至少一个目标实例上与主配置不同
``conflict``  有两个以上功能抢同一个键（写进游戏会互相顶掉，必须解决）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .diff import BindingDiff, ChangeKind, DiffTable
from .keycodes import UNBOUND, KeyCombo
from .naming import BindingInfo

#: 状态常量
STATE_FREE = "free"
STATE_USED = "used"
STATE_DIFF = "diff"
STATE_CONFLICT = "conflict"

#: 状态 -> 中文名（给下拉框和详情面板用）
STATE_NAMES: dict[str, str] = {
    STATE_FREE: "空闲",
    STATE_USED: "已绑定",
    STATE_DIFF: "与主配置不同",
    STATE_CONFLICT: "冲突",
}

#: 界面上的展示顺序：先看问题，再看正常，最后才是空闲
STATE_ORDER: tuple[str, ...] = (STATE_CONFLICT, STATE_DIFF, STATE_USED, STATE_FREE)

#: 窄地方（勾选框）用的短名，「与主配置不同」在工具条上太占地方
STATE_SHORT: dict[str, str] = {
    STATE_FREE: "空闲",
    STATE_USED: "已绑定",
    STATE_DIFF: "不同",
    STATE_CONFLICT: "冲突",
}

#: 值差异比「某个实例根本没有这个功能」更值得提醒，所以排序时优先级更高
_KIND_PRIORITY: dict[ChangeKind, int] = {
    ChangeKind.DIFFERS: 6,
    ChangeKind.SEMANTIC: 5,
    ChangeKind.TARGET_UNBOUND: 4,
    ChangeKind.PROFILE_UNBOUND: 4,
    ChangeKind.ONLY_IN_TARGET: 2,
    ChangeKind.ONLY_IN_PROFILE: 1,
    ChangeKind.SAME: 0,
}


@dataclass
class KeyBindingRef:
    """占用某个键的一个功能。"""

    binding_name: str
    display: str
    group: str
    owner_name: str
    value: KeyCombo
    kind: ChangeKind
    is_vanilla: bool = False
    semantic_action: str | None = None

    @property
    def label(self) -> str:
        return f"{self.display}  [{self.group}]"

    @property
    def differs(self) -> bool:
        return self.kind is not ChangeKind.SAME

    def detail_line(self) -> str:
        tail = ""
        if self.differs:
            tail = f"   —— {CHANGE_TEXT.get(self.kind, self.kind.value)}"
        return f"{self.label}{tail}"

    def search_text(self) -> str:
        return f"{self.binding_name} {self.display} {self.group} {self.owner_name}".lower()


@dataclass
class KeyUsage:
    """一个键（``key.keyboard.m`` / ``key.mouse.middle`` …）上的占用情况。"""

    code: str
    bindings: list[KeyBindingRef] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.bindings)

    @property
    def state(self) -> str:
        if not self.bindings:
            return STATE_FREE
        if len(self.bindings) > 1:
            return STATE_CONFLICT
        if any(b.differs for b in self.bindings):
            return STATE_DIFF
        return STATE_USED

    @property
    def state_name(self) -> str:
        return STATE_NAMES.get(self.state, self.state)

    def sort_bindings(self) -> None:
        self.bindings.sort(key=lambda b: (not b.is_vanilla, b.display.lower(),
                                          b.binding_name))

    def summary_lines(self) -> list[str]:
        return [b.detail_line() for b in self.bindings]


#: 复用一个中文说明表，避免和 diff.CHANGE_META 的措辞漂移
CHANGE_TEXT: dict[ChangeKind, str] = {
    ChangeKind.DIFFERS: "与主配置不一致",
    ChangeKind.TARGET_UNBOUND: "目标实例尚未绑定",
    ChangeKind.PROFILE_UNBOUND: "主配置未绑定",
    ChangeKind.ONLY_IN_TARGET: "主配置里没有这个功能",
    ChangeKind.ONLY_IN_PROFILE: "目标实例没有这个功能",
    ChangeKind.SEMANTIC: "同功能对齐（绑定名不同）",
}


def _matches(info: BindingInfo, keyword: str | None, group: str | None,
             owner: str | None = None) -> bool:
    if group and info.group != group:
        return False
    if owner and (info.owner_name or "") != owner:
        return False
    if keyword:
        hay = " ".join(filter(None, (
            info.binding_name, info.translation_key, info.display,
            info.group, info.owner_name, info.owner_mod,
        ))).lower()
        for token in str(keyword).lower().split():
            if token not in hay:
                return False
    return True


def _overall_kind(row: BindingDiff, targets: list[str],
                  focus: str | None) -> ChangeKind:
    if focus is not None:
        return row.kind_for(focus)
    worst = ChangeKind.SAME
    for key in targets:
        kind = row.kind_for(key)
        if _KIND_PRIORITY.get(kind, 0) > _KIND_PRIORITY.get(worst, 0):
            worst = kind
    return worst


def build_key_usage(table: DiffTable,
                    instance_key: str | None = None,
                    *,
                    targets: list[str] | None = None,
                    keyword: str | None = None,
                    group: str | None = None,
                    owner: str | None = None) -> dict[str, KeyUsage]:
    """算出键盘上每个键的占用情况。

    ``instance_key`` 为 ``None`` 时看主配置，否则看该实例。``targets`` 默认取
    ``table.instance_keys``，主配置视角下用于判断「和谁不一样」。
    """
    known = set(table.instance_keys)
    if targets is None:
        target_keys = list(table.instance_keys)
    else:
        target_keys = [t for t in targets if t in known]
    if instance_key is not None and instance_key not in known:
        instance_key = None

    out: dict[str, KeyUsage] = {}
    for row in table.rows:
        if not _matches(row.info, keyword, group, owner):
            continue
        value = (row.profile_value if instance_key is None
                 else row.instance_values.get(instance_key))
        if value is None or not value.code or value.code == UNBOUND:
            continue
        usage = out.get(value.code)
        if usage is None:
            usage = out[value.code] = KeyUsage(code=value.code)
        usage.bindings.append(KeyBindingRef(
            binding_name=row.binding_name,
            display=row.info.display,
            group=row.info.group,
            owner_name=row.info.owner_name,
            value=value,
            kind=_overall_kind(row, target_keys, instance_key),
            is_vanilla=row.info.is_vanilla,
            semantic_action=row.info.semantic_action,
        ))

    for usage in out.values():
        usage.sort_bindings()
    return out


def state_counts(usages: dict[str, KeyUsage]) -> dict[str, int]:
    """各状态各有多少个键（给状态栏/图例用）。"""
    out = {STATE_FREE: 0, STATE_USED: 0, STATE_DIFF: 0, STATE_CONFLICT: 0}
    for usage in usages.values():
        out[usage.state] = out.get(usage.state, 0) + 1
    return out


def groups_of(table: DiffTable) -> list[str]:
    """表里出现过的所有分组名，去重排序（过滤下拉框用）。"""
    return sorted({row.info.group for row in table.rows if row.info.group})


def owners_of(table: DiffTable) -> list[str]:
    """表里出现过的所有归属 Mod 名，去重排序。"""
    return sorted({row.info.owner_name for row in table.rows if row.info.owner_name})


def conflict_usages(usages: dict[str, KeyUsage]) -> list[KeyUsage]:
    """所有「一个键被多个功能抢」的项，按冲突数从多到少排。"""
    items = [u for u in usages.values() if u.state == STATE_CONFLICT]
    items.sort(key=lambda u: (-u.count, u.code))
    return items


def apply_state_filter(usages: dict[str, KeyUsage],
                       allowed: set[str] | None) -> dict[str, KeyUsage]:
    """按状态过滤：不在 ``allowed`` 里的键会被清空，于是在键盘上显示成「空闲」。

    键盘图没法真的把某个键藏起来，所以「过滤掉」的视觉表现就是回到空闲灰。
    """
    if not allowed:
        return usages
    out: dict[str, KeyUsage] = {}
    for code, usage in usages.items():
        if usage.state in allowed:
            out[code] = usage
    return out
