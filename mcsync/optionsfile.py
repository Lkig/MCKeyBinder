# -*- coding: utf-8 -*-
"""``options.txt`` 的保真读写。

关键约束（全部由真实文件实测得出）：

* 编码 **UTF-8 无 BOM**；实测文件 285 行全部是 **CRLF**，且以换行结尾。
  写错编码/换行会让 Minecraft 认为文件损坏并**整份重置选项**。
* **绝不整文件替换**：只按条目 merge，未知行、注释行、空行原样保留在原位置。
* 每行格式 ``名字:值``，以**第一个**冒号切分（值里可能还有冒号，例如
  ``key_key.jei.toggleOverlay:key.keyboard.o:CONTROL`` 与 IPv6 形式的 ``lastServer``）。
* 按键行以 ``key_`` 开头；绑定名 = ``key_`` + 翻译键。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from .keycodes import KeyCombo, UNBOUND, normalise_code

#: 按键行的名字前缀
KEY_PREFIX = "key_"

#: Minecraft 自己的选项键（非按键）里，这些是「实例相关」的，
#: 跨整合包同步通常没有意义甚至有副作用，默认排除。
INSTANCE_SPECIFIC_OPTIONS: frozenset[str] = frozenset({
    "fullscreen",
    "fullscreenResolution",
    "overrideWidth",
    "overrideHeight",
    "lastServer",
    "tutorialStep",
    "resourcePacks",
    "incompatibleResourcePacks",
    "soundDevice",
    "version",
    "joinedFirstServer",
    "skipMultiplayerWarning",
    "onboardAccessibility",
    "glDebugVerbosity",
    "chatVisibility",
})

#: 想同步「其他设置」时，默认勾选的稳妥集合
DEFAULT_SYNCED_OPTIONS: tuple[str, ...] = (
    "lang",
    "fov",
    "fovEffectScale",
    "darknessEffectScale",
    "gamma",
    "guiScale",
    "maxFps",
    "renderDistance",
    "simulationDistance",
    "entityDistanceScaling",
    "ao",
    "biomeBlendRadius",
    "graphicsMode",
    "particles",
    "mipmapLevels",
    "entityShadows",
    "enableVsync",
    "bobView",
    "autoJump",
    "toggleCrouch",
    "toggleSprint",
    "mouseSensitivity",
    "mouseWheelSensitivity",
    "invertYMouse",
    "rawMouseInput",
    "damageTiltStrength",
    "screenEffectScale",
    "chatOpacity",
    "chatScale",
    "chatLineSpacing",
    "chatWidth",
    "chatHeightFocused",
    "chatHeightUnfocused",
    "chatColors",
    "chatLinks",
    "chatLinksPrompt",
    "textBackgroundOpacity",
    "backgroundForChatOnly",
    "advancedItemTooltips",
    "showSubtitles",
    "notificationDisplayTime",
    "attackIndicator",
    "mainHand",
    "hideMatchedNames",
    "hideLightningFlashes",
    "hideSplashTexts",
    "darkMojangStudiosBackground",
    "menuBackgroundBlurriness",
    "panoramaScrollSpeed",
    "glintSpeed",
    "glintStrength",
    "narrator",
    "highContrast",
    "directionalAudio",
    "allowServerListing",
    "realmsNotifications",
    "autoSuggestions",
    "pauseOnLostFocus",
    "discrete_mouse_scroll",
    "invertMouseX",
    "allowCursorChanges",
    "showAutosaveIndicator",
)

_SOUND_PREFIX = "soundCategory_"
_MODEL_PREFIX = "modelPart_"


@dataclass
class OptionLine:
    """``options.txt`` 里的一行，保留原始文本以保证能原样写回。"""

    raw: str
    name: str | None = None
    value: str | None = None
    dirty: bool = False
    is_new: bool = False

    @classmethod
    def parse(cls, raw: str) -> "OptionLine":
        stripped = raw.strip()
        if not stripped or ":" not in stripped:
            return cls(raw=raw, name=None, value=None)
        name, value = stripped.split(":", 1)
        return cls(raw=raw, name=name, value=value)

    def render(self) -> str:
        if self.name is None:
            return self.raw
        if not self.dirty and not self.is_new:
            return self.raw
        return f"{self.name}:{self.value}"

    @property
    def is_keybind(self) -> bool:
        return bool(self.name) and self.name.startswith(KEY_PREFIX)

    @property
    def binding_name(self) -> str | None:
        """按键行返回完整绑定名（含 ``key_`` 前缀）。"""
        return self.name if self.is_keybind else None

    @property
    def translation_key(self) -> str | None:
        """按键行返回翻译键（去掉 ``key_`` 前缀）。

        例：``key_key.jei.showRecipe`` -> ``key.jei.showRecipe``
            ``key_gui.xaero_open_map``  -> ``gui.xaero_open_map``
        """
        if not self.is_keybind:
            return None
        assert self.name is not None
        return self.name[len(KEY_PREFIX):]


class OptionsFile:
    """一个 ``options.txt`` 的内存表示，支持保序、保编码地原地修改。"""

    def __init__(self, path: os.PathLike[str] | str, lines: list[OptionLine],
                 newline: str = "\r\n", has_bom: bool = False,
                 trailing_newline: bool = True, existed: bool = True) -> None:
        self.path = Path(path)
        self.lines = lines
        self.newline = newline
        self.has_bom = has_bom
        self.trailing_newline = trailing_newline
        self.existed = existed
        self._index: dict[str, OptionLine] = {}
        self._rebuild_index()

    # -- 载入 ------------------------------------------------------------
    @classmethod
    def load(cls, path: os.PathLike[str] | str) -> "OptionsFile":
        p = Path(path)
        if not p.is_file():
            return cls(p, [], existed=False)

        data = p.read_bytes()
        has_bom = data.startswith(b"\xef\xbb\xbf")
        if has_bom:
            data = data[3:]

        # 换行符：以出现次数多的为准，单行文件按 CRLF 处理
        crlf = data.count(b"\r\n")
        bare_lf = data.count(b"\n") - crlf
        newline = "\r\n" if crlf >= bare_lf else "\n"

        text = data.decode("utf-8", errors="surrogateescape")
        trailing = text.endswith("\n")
        raw_lines = text.splitlines()
        lines = [OptionLine.parse(line) for line in raw_lines]
        return cls(p, lines, newline=newline, has_bom=has_bom,
                   trailing_newline=trailing, existed=True)

    # -- 索引 ------------------------------------------------------------
    def _rebuild_index(self) -> None:
        self._index = {}
        for line in self.lines:
            if line.name is not None:
                # 重复条目时后写的生效，与 Minecraft 行为一致
                self._index[line.name] = line

    # -- 读取 ------------------------------------------------------------
    def get(self, name: str, default: str | None = None) -> str | None:
        line = self._index.get(name)
        return line.value if line is not None else default

    def has(self, name: str) -> bool:
        return name in self._index

    def __contains__(self, name: object) -> bool:
        return name in self._index

    def __iter__(self) -> Iterator[OptionLine]:
        return iter(self.lines)

    # -- 写入 ------------------------------------------------------------
    def set(self, name: str, value: str) -> bool:
        """设置一个条目。已存在则原地更新，否则插入到合适位置。

        返回是否为「新增」。
        """
        line = self._index.get(name)
        if line is not None:
            if line.value != value:
                line.value = value
                line.dirty = True
            return False
        new_line = OptionLine(raw="", name=name, value=value,
                              dirty=True, is_new=True)
        self._insert(new_line)
        self._index[name] = new_line
        return True

    def remove(self, name: str) -> bool:
        line = self._index.pop(name, None)
        if line is None:
            return False
        self.lines = [ln for ln in self.lines if ln is not line]
        return True

    def _insert(self, line: OptionLine) -> None:
        """把新条目插到语义相近的区域，尽量贴近 Minecraft 自己写出的顺序。"""
        name = line.name or ""

        if name.startswith(KEY_PREFIX):
            # 插到最后一条按键行之后，保持按键区块连续
            last_key = -1
            for i, ln in enumerate(self.lines):
                if ln.is_keybind:
                    last_key = i
            if last_key >= 0:
                self.lines.insert(last_key + 1, line)
            else:
                self.lines.append(line)
            return

        if name.startswith(_SOUND_PREFIX):
            last = -1
            for i, ln in enumerate(self.lines):
                if ln.name and ln.name.startswith(_SOUND_PREFIX):
                    last = i
            self.lines.insert(last + 1 if last >= 0 else len(self.lines), line)
            return

        if name.startswith(_MODEL_PREFIX):
            self.lines.append(line)
            return

        # 普通选项：插到最后一条普通选项之后（即第一个按键行之前）
        first_key = len(self.lines)
        for i, ln in enumerate(self.lines):
            if ln.is_keybind:
                first_key = i
                break
        # 再往前跳过 soundCategory / modelPart 区块
        insert_at = first_key
        self.lines.insert(insert_at, line)

    # -- 按键专用视图 ----------------------------------------------------
    def keybinds(self) -> dict[str, KeyCombo]:
        """返回 ``{绑定名: KeyCombo}``。"""
        out: dict[str, KeyCombo] = {}
        for line in self.lines:
            if line.is_keybind and line.name is not None:
                out[line.name] = KeyCombo.parse(line.value)
        return out

    def keybind_translation_keys(self) -> dict[str, str]:
        """返回 ``{绑定名: 翻译键}``。"""
        out: dict[str, str] = {}
        for line in self.lines:
            tk = line.translation_key
            if tk is not None and line.name is not None:
                out[line.name] = tk
        return out

    def keybind_raw(self) -> dict[str, str]:
        """返回 ``{绑定名: 原始值字符串}``。"""
        out: dict[str, str] = {}
        for line in self.lines:
            if line.is_keybind and line.name is not None:
                out[line.name] = line.value or ""
        return out

    def code_style(self) -> str:
        """这个文件用的是 ``named`` 还是 ``legacy`` 键码风格。"""
        from .keycodes import detect_code_style
        return detect_code_style(v for v in self.keybind_raw().values())

    def non_key_options(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in self.lines:
            if line.name is not None and not line.is_keybind:
                out[line.name] = line.value or ""
        return out

    # -- 保存 ------------------------------------------------------------
    def render(self) -> str:
        body = self.newline.join(line.render().rstrip("\r\n") for line in self.lines)
        if self.trailing_newline:
            body += self.newline
        return body

    def save(self, path: os.PathLike[str] | str | None = None) -> Path:
        """写回文件。始终 UTF-8 无 BOM，沿用原换行符。"""
        target = Path(path) if path is not None else self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        text = self.render()
        data = text.encode("utf-8", errors="surrogateescape")
        if self.has_bom:
            data = b"\xef\xbb\xbf" + data

        # 先写临时文件再原子替换，避免中途失败留下半个文件
        tmp = target.with_name(target.name + ".mcsync.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)

        for line in self.lines:
            line.dirty = False
            line.is_new = False
        return target

    # -- 统计 ------------------------------------------------------------
    @property
    def keybind_count(self) -> int:
        return sum(1 for line in self.lines if line.is_keybind)


# --------------------------------------------------------------------------
# 辅助
# --------------------------------------------------------------------------

def is_valid_binding_name(name: str) -> bool:
    """粗略校验绑定名合法性，防止把脏数据写进文件。"""
    if not name.startswith(KEY_PREFIX):
        return False
    rest = name[len(KEY_PREFIX):]
    if not rest:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_.\-/]+", rest))


def merge_keybinds(target: OptionsFile, source: dict[str, KeyCombo],
                   only_existing: bool = True) -> tuple[list[str], list[str]]:
    """把 ``source`` 里的按键合并进 ``target``。

    ``only_existing=True`` 时只更新目标已有的绑定名（这是默认且唯一安全的做法：
    写目标不认识的按键，会被 Minecraft 在下次退出时静默删除）。

    返回 ``(已写入, 被跳过)`` 两个绑定名列表。
    """
    written: list[str] = []
    skipped: list[str] = []
    existing = target.keybinds()
    for name, combo in source.items():
        if name not in existing:
            if only_existing:
                skipped.append(name)
                continue
        if existing.get(name) == combo and name in existing:
            continue
        target.set(name, combo.to_options())
        written.append(name)
    return written, skipped
