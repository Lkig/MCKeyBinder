# -*- coding: utf-8 -*-
"""同步基线快照（三方合并用）。

**为什么需要它**：主配置是「我想要的键位」，目标实例是「它现在的键位」。
只比较这两者的话，就没法区分下面两种情况：

* 目标实例里 ``key_key.screenshot`` 是「未绑定」，是因为这个整合包默认
  就没绑 —— 主配置里有值，应该绑上；
* 目标实例里它是「未绑定」，是因为**我刚刚在游戏里故意解绑了** ——
  这时再按主配置绑回去就是帮倒忙。

两者在主配置/目标两份文件里长得一模一样，只有引入第三份信息才能区分：
**上次同步结束时这个文件长什么样**。如果某个按键现在和基线不一样，
说明是我们同步之后被人（或游戏）改过的，那就尊重现状、跳过它。

基线在每次同步写完之后重新采集（把写完之后真实的键位存下来），
所以「同步 -> 在游戏里改键 -> 再同步」这个顺序下，用户的改动不会被盖掉。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Mapping

from .atomicio import write_text_atomic

#: 状态文件名（放在数据目录下，跟主配置、备份在一起）
STATE_NAME = "sync_state.json"
STATE_FORMAT = "mcsync-state"
STATE_VERSION = 1

#: 单个实例最多记多少条键位快照（防止用户玩了几百个整合包把文件撑大）
MAX_BINDINGS = 4000


@dataclass
class InstanceSnapshot:
    """某个目标实例「上次同步结束时」的键位。"""

    at: str = ""
    bindings: dict[str, str] = field(default_factory=dict)

    def value_of(self, binding_name: str) -> str | None:
        return self.bindings.get(binding_name)


@dataclass
class SyncState:
    """所有实例的同步基线。"""

    path: Path
    instances: dict[str, InstanceSnapshot] = field(default_factory=dict)

    # -- 载入 / 保存 ---------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "SyncState":
        state = cls(path=Path(path))
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return state
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return state
        if not isinstance(data, dict):
            return state
        for key, item in (data.get("instances") or {}).items():
            if not isinstance(item, dict):
                continue
            bindings = item.get("bindings")
            if not isinstance(bindings, dict):
                bindings = {}
            state.instances[str(key)] = InstanceSnapshot(
                at=str(item.get("at") or ""),
                bindings={str(k): str(v) for k, v in bindings.items()},
            )
        return state

    def to_dict(self) -> dict:
        return {
            "format": STATE_FORMAT,
            "version": STATE_VERSION,
            "instances": {
                key: {"at": snap.at, "bindings": snap.bindings}
                for key, snap in self.instances.items()
            },
        }

    def save(self) -> bool:
        text = json.dumps(self.to_dict(), ensure_ascii=False, indent=1)
        return write_text_atomic(self.path, text, strict=False)

    # -- 查询 / 记录 ---------------------------------------------------
    def snapshot(self, instance_key: str) -> InstanceSnapshot | None:
        return self.instances.get(instance_key)

    def has_snapshot(self, instance_key: str) -> bool:
        snap = self.instances.get(instance_key)
        return bool(snap and snap.bindings)

    def manually_changed(self, instance_key: str, binding_name: str,
                         current: str | None) -> bool:
        """现在的值和基线不一样 -> 是我们上次同步之后被改过的。

        没有基线（这个实例从没同步过）、或基线里没有这一条（上次同步时
        目标里根本没有这个绑定名）时一律返回 ``False``，也就是照常同步，
        免得第一次同步就什么都不做。
        """
        snap = self.instances.get(instance_key)
        if snap is None:
            return False
        baseline = snap.bindings.get(binding_name)
        if baseline is None:
            return False
        return baseline != current

    def record(self, instance_key: str,
               bindings: Mapping[str, str],
               when: str | None = None) -> None:
        """记录「这次同步结束时」的键位。"""
        if not bindings:
            return
        items = sorted(bindings.items())[:MAX_BINDINGS]
        self.instances[str(instance_key)] = InstanceSnapshot(
            at=when or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            bindings=dict(items),
        )

    def forget(self, instance_key: str) -> bool:
        return self.instances.pop(instance_key, None) is not None

    def clear(self) -> None:
        self.instances.clear()

    @property
    def instance_count(self) -> int:
        return len(self.instances)
