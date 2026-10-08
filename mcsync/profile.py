# -*- coding: utf-8 -*-
"""主配置（Profile）—— 一份可复用的按键方案。

借鉴对象：
  * ``OptionSync``（2016）的「命名存档位 + 载入」交互
  * ``FCL`` 启动器的「键位分享码」形态
  * ``Configured Defaults`` 的「按条目 merge，绝不整文件替换」写入策略

一份 Profile 包含三类内容：

``keybinds``
    绑定名 -> 键位组合。这是核心，也是唯一默认同步的东西。
``options``
    其他 ``options.txt`` 条目（视野、GUI 缩放、音量……），可选。
``files``
    模组自己配置文件里的快捷键，以「相对实例目录的路径 -> 内容摘要」表示。

Profile 存成 UTF-8 JSON，可以直接发给别人导入。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .atomicio import write_text_atomic
from .keycodes import KeyCombo
from .optionsfile import OptionsFile

PROFILE_FORMAT = "mcsync-profile"
PROFILE_VERSION = 1


@dataclass
class Profile:
    """一份按键方案。"""

    name: str = "主配置"
    keybinds: dict[str, KeyCombo] = field(default_factory=dict)
    options: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    created: str = ""
    updated: str = ""
    source: str = ""
    note: str = ""

    # -- 构造 ------------------------------------------------------------
    @classmethod
    def capture(cls, options: OptionsFile, name: str = "主配置",
                source: str = "", include_options: Iterable[str] | None = None,
                include_files: Mapping[str, str] | None = None) -> "Profile":
        """从一个实例的 options.txt 抓取出一份配置。"""
        now = _now()
        profile = cls(name=name, created=now, updated=now, source=source)
        profile.keybinds = dict(options.keybinds())
        if include_options:
            all_options = options.non_key_options()
            profile.options = {k: all_options[k] for k in include_options
                               if k in all_options}
        if include_files:
            profile.files = dict(include_files)
        return profile

    # -- 查询 ------------------------------------------------------------
    @property
    def binding_count(self) -> int:
        return len(self.keybinds)

    def bound_count(self) -> int:
        return sum(1 for c in self.keybinds.values() if c.bound)

    def get(self, binding_name: str) -> KeyCombo | None:
        return self.keybinds.get(binding_name)

    def __len__(self) -> int:
        return len(self.keybinds)

    def __iter__(self) -> Iterator[tuple[str, KeyCombo]]:
        return iter(self.keybinds.items())

    # -- 编辑 ------------------------------------------------------------
    def set(self, binding_name: str, combo: KeyCombo) -> None:
        self.keybinds[binding_name] = combo
        self.updated = _now()

    def set_options(self, values: Mapping[str, str]) -> None:
        self.options.update(values)
        self.updated = _now()

    def rename(self, new_name: str) -> None:
        self.name = new_name
        self.updated = _now()

    def copy_as(self, new_name: str) -> "Profile":
        return Profile(
            name=new_name,
            keybinds=dict(self.keybinds),
            options=dict(self.options),
            files=dict(self.files),
            created=_now(),
            updated=_now(),
            source=self.source,
            note=self.note,
        )

    # -- 序列化 ----------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "format": PROFILE_FORMAT,
            "version": PROFILE_VERSION,
            "name": self.name,
            "created": self.created,
            "updated": self.updated,
            "source": self.source,
            "note": self.note,
            "keybinds": {k: v.to_options() for k, v in sorted(self.keybinds.items())},
            "options": dict(sorted(self.options.items())),
            "files": dict(sorted(self.files.items())),
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "Profile":
        keybinds: dict[str, KeyCombo] = {}
        for name, raw in (data.get("keybinds") or {}).items():
            if isinstance(raw, str):
                keybinds[name] = KeyCombo.parse(raw)
        return cls(
            name=str(data.get("name") or "主配置"),
            keybinds=keybinds,
            options={k: str(v) for k, v in (data.get("options") or {}).items()},
            files={k: str(v) for k, v in (data.get("files") or {}).items()},
            created=str(data.get("created") or ""),
            updated=str(data.get("updated") or ""),
            source=str(data.get("source") or ""),
            note=str(data.get("note") or ""),
        )

    def save(self, path: Path) -> Path:
        self.updated = _now()
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        write_text_atomic(Path(path), payload)
        return path

    @classmethod
    def load(cls, path: Path) -> "Profile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("配置文件格式不对：顶层不是对象")
        fmt = data.get("format")
        if fmt and fmt != PROFILE_FORMAT:
            raise ValueError(f"不是 MCKeyBinder 按键同步器的配置文件（format={fmt}）")
        version = data.get("version")
        if isinstance(version, int) and version > PROFILE_VERSION:
            raise ValueError(f"配置文件版本 {version} 比当前程序支持的 {PROFILE_VERSION} 新")
        return cls.from_dict(data)

    # -- 与另一个配置比较 -------------------------------------------------
    def diff(self, other: "Profile") -> dict[str, tuple[KeyCombo | None, KeyCombo | None]]:
        """返回 ``{绑定名: (self 的值, other 的值)}``，只包含不同的项。"""
        out: dict[str, tuple[KeyCombo | None, KeyCombo | None]] = {}
        for name in set(self.keybinds) | set(other.keybinds):
            a = self.keybinds.get(name)
            b = other.keybinds.get(name)
            if a != b:
                out[name] = (a, b)
        return out


class ProfileStore:
    """管理磁盘上的多份配置。"""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def list(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return sorted(self.directory.glob("*.json"),
                      key=lambda p: p.stat().st_mtime, reverse=True)

    def load_all(self) -> list[Profile]:
        out: list[Profile] = []
        for path in self.list():
            try:
                out.append(Profile.load(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return out

    def path_for(self, name: str) -> Path:
        safe = "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "profile"
        return self.directory / f"{safe}.json"

    def save(self, profile: Profile) -> Path:
        return profile.save(self.path_for(profile.name))

    def delete(self, name: str) -> bool:
        path = self.path_for(name)
        if path.is_file():
            path.unlink()
            return True
        return False


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
