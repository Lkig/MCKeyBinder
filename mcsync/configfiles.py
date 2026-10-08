# -*- coding: utf-8 -*-
"""模组自身配置文件里的快捷键同步。

调研结论：**绝大多数 mod 的按键都存在 ``options.txt`` 里**（Xaero、JourneyMap、
JEI 的官方文档都明确说按键在「原版控制菜单」里），所以这一块是补充而非主线。

但确实有 mod 把快捷键写在自己的配置里。本模块不硬编码任何 mod 的格式，
而是**扫描实例目录、自动识别「疑似含快捷键的配置文件」**，然后让用户决定
要把哪些文件从源实例复制到目标实例。这也是 ``Default Options`` 的
``extra/`` 机制在做的事。
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

#: 配置文件允许的扩展名
CONFIG_SUFFIXES = (".json", ".json5", ".toml", ".cfg", ".ini", ".properties",
                   ".txt", ".yml", ".yaml", ".conf")

#: 扫描时跳过的目录
SKIP_DIR_NAMES = frozenset({
    "logs", "crash-reports", "screenshots", "saves", "resourcepacks",
    "shaderpacks", "mods", "libraries", "versions", "assets", "cache",
    "downloads", "backups", "simplebackups", ".git", "local", "usercache",
    "data", "patchouli_books", "schematics", "defaultconfigs",
})

#: 「看起来像快捷键」的键名
KEY_LIKE_NAMES = re.compile(
    r"(key|keybind|hotkey|shortcut|binding|shortcut_key|keys?\b)",
    re.IGNORECASE,
)

#: 「看起来像键码」的值
KEY_LIKE_VALUES = re.compile(
    r"^(key\.(keyboard|mouse)\.|KEY_|GLFW_|VK_|scancode)",
    re.IGNORECASE,
)

#: 值形如单字母 / F1-F24 / 常见键名
SIMPLE_KEY_VALUE = re.compile(
    r"^([a-z]|f([1-9]|1[0-9]|2[0-4])|space|tab|enter|escape|shift|control|ctrl|alt"
    r"|left|right|up|down|numpad[0-9]|mouse[0-9]?|button[0-9]?)$",
    re.IGNORECASE,
)


@dataclass
class ConfigCandidate:
    """一个疑似含快捷键的配置文件。"""

    relative_path: str
    size: int
    key_fields: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def confidence(self) -> int:
        return len(self.key_fields)


def scan_config_dir(game_dir: Path, max_files: int = 4000,
                    cancel: Callable[[], bool] | None = None) -> list[ConfigCandidate]:
    """在实例目录里找出疑似含快捷键的配置文件。"""
    out: list[ConfigCandidate] = []
    if not game_dir.is_dir():
        return out

    checked = 0
    for path in _iter_config_files(game_dir):
        if cancel is not None and cancel():
            break
        checked += 1
        if checked > max_files:
            break
        candidate = _inspect(path, game_dir)
        if candidate is not None:
            out.append(candidate)

    out.sort(key=lambda c: (-c.confidence, c.relative_path))
    return out


def _iter_config_files(game_dir: Path) -> Iterable[Path]:
    for path in game_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in CONFIG_SUFFIXES:
            continue
        try:
            rel_parts = path.relative_to(game_dir).parts
        except ValueError:
            continue
        if any(part.lower() in SKIP_DIR_NAMES for part in rel_parts[:-1]):
            continue
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
        except OSError:
            continue
        yield path


def _inspect(path: Path, game_dir: Path) -> ConfigCandidate | None:
    """判断一个文件是否像「存了快捷键的配置」。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.strip():
        return None

    rel = str(path.relative_to(game_dir))
    fields: list[str] = []

    suffix = path.suffix.lower()
    if suffix in (".json", ".json5"):
        fields = _inspect_json(text)
    else:
        fields = _inspect_text(text)

    if not fields:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        size = len(text)
    return ConfigCandidate(relative_path=rel, size=size, key_fields=fields[:20],
                           reason=f"发现 {len(fields)} 个疑似快捷键配置项")


def _inspect_json(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _inspect_text(text)
    found: list[str] = []

    def walk(node, prefix: str = "") -> None:
        if len(found) >= 40:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                name = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(value, (dict, list)):
                    walk(value, name)
                elif isinstance(value, str):
                    if KEY_LIKE_VALUES.match(value.strip()) or (
                            KEY_LIKE_NAMES.search(str(key))
                            and SIMPLE_KEY_VALUE.match(value.strip())):
                        found.append(name)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{prefix}[{index}]")

    walk(data)
    return found


def _inspect_text(text: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        if len(found) >= 40:
            break
        line = line.strip()
        if not line or line.startswith(("#", "//", ";")):
            continue
        if "=" not in line and ":" not in line:
            continue
        sep = "=" if "=" in line else ":"
        name, _, value = line.partition(sep)
        name = name.strip().strip('"').strip("'")
        value = value.strip().strip('"').strip("'").rstrip(",")
        if not name or not value:
            continue
        if KEY_LIKE_VALUES.match(value) or (
                KEY_LIKE_NAMES.search(name) and SIMPLE_KEY_VALUE.match(value)):
            found.append(name)
    return found


# --------------------------------------------------------------------------
# 复制
# --------------------------------------------------------------------------

@dataclass
class FileSyncResult:
    source: str
    target: Path
    ok: bool
    error: str = ""
    backup: Path | None = None


def sync_config_files(source_game_dir: Path,
                      target_game_dirs: Sequence[Path],
                      relative_paths: Sequence[str],
                      backup_manager=None) -> list[FileSyncResult]:
    """把源实例里的指定配置文件复制到各目标实例。

    覆盖前先备份目标文件。目标里对应父目录不存在时会自动创建。
    """
    results: list[FileSyncResult] = []

    for rel in relative_paths:
        source = source_game_dir / rel
        if not source.is_file():
            for target_dir in target_game_dirs:
                results.append(FileSyncResult(
                    source=rel, target=target_dir / rel, ok=False,
                    error="源实例里找不到这个文件",
                ))
            continue

        for target_dir in target_game_dirs:
            target = target_dir / rel
            if source.resolve() == target.resolve():
                continue
            result = FileSyncResult(source=rel, target=target, ok=False)

            if target.is_file() and backup_manager is not None:
                record = backup_manager.create(
                    [(target, target_dir.name, "config")],
                    label="配置文件同步前", note=f"来自 {source_game_dir.name}")
                if record is not None:
                    result.backup = record.directory

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                result.ok = True
            except OSError as exc:
                result.error = str(exc)
            results.append(result)

    return results
