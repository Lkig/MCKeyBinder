"""原版中文语言文件。

`options.txt` 里的设置项名是英文驼峰（`bobView`、`chatOpacity`…），直接摆给
用户看很不友好。原版的翻译在 `assets/minecraft/lang/zh_cn.json` 里，而这份
文件**不在 client jar 中**（jar 里只有 `en_us.json`），它是按资源索引下载下来的
资源对象：

    versions/<版本>/<版本>.json  ->  assetIndex.id
    assets/indexes/<id>.json     ->  objects["minecraft/lang/zh_cn.json"].hash
    assets/objects/<hash[:2]>/<hash>   <- 真正的 JSON

这里把这条链路封起来，顺便给出「设置项名 -> 中文」的解析规则。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

LANG_ENTRY = "minecraft/lang/zh_cn.json"

#: 语言文件很大（8500+ 条），同一个文件只解析一次。
_CACHE: dict[tuple[str, int, int], Mapping[str, str]] = {}


# --------------------------------------------------------------------------
# 设置项名 -> 翻译键
# --------------------------------------------------------------------------

#: 名字和翻译键对不上的（逐个对着 1.21.1 的 zh_cn.json 核过）
OPTION_ALIASES: dict[str, str] = {
    "backgroundForChatOnly": "options.accessibility.text_background",
    "bobView": "options.viewBobbing",
    "chatColors": "options.chat.color",
    "chatDelay": "options.chat.delay",
    "chatHeightFocused": "options.chat.height.focused",
    "chatHeightUnfocused": "options.chat.height.unfocused",
    "chatLineSpacing": "options.chat.line_spacing",
    "chatLinks": "options.chat.links",
    "chatLinksPrompt": "options.chat.links.prompt",
    "chatOpacity": "options.chat.opacity",
    "chatScale": "options.chat.scale",
    "chatVisibility": "options.chat.visibility",
    "chatWidth": "options.chat.width",
    "darkMojangStudiosBackground": "options.darkMojangStudiosBackgroundColor",
    "enableVsync": "options.vsync",
    "graphicsMode": "options.graphics",
    "hideServerAddress": "options.hideServerAddress",
    "highContrast": "options.accessibility.high_contrast",
    "invertYMouse": "options.invertMouse",
    "lang": "options.language",
    "maxFps": "options.framerateLimit",
    "menuBackgroundBlurriness": "options.accessibility.menu_background_blurriness",
    "mouseSensitivity": "options.sensitivity",
    "narratorHotkey": "options.accessibility.narrator_hotkey",
    "notificationDisplayTime": "options.notifications.display_time",
    "onboardAccessibility": "options.accessibility",
    "panoramaScrollSpeed": "options.accessibility.panorama_speed",
    "pauseOnLostFocus": "options.pauseOnLostFocus",
    "soundDevice": "options.audioDevice",
    "showAutosaveIndicator": "options.autosaveIndicator",
    "textBackgroundOpacity": "options.accessibility.text_background_opacity",
}

#: 语言文件里压根没有、但确实该给个中文名的（工具栏配置项、内部状态项）
OPTION_MANUAL: dict[str, str] = {
    "advancedItemTooltips": "高级物品信息",
    "autoSuggestions": "命令自动补全",
    "toggleSprint": "切换疾跑",
    "toggleCrouch": "切换潜行",
    "skipMultiplayerWarning": "跳过多人游戏警告",
    "hideBundleTutorial": "隐藏收纳袋教程",
    "useNativeTransport": "使用原生网络传输",
    "syncChunkWrites": "同步区块写入",
    "glDebugVerbosity": "OpenGL 调试信息级别",
    "resourcePacks": "资源包",
    "incompatibleResourcePacks": "不兼容的资源包",
    "telemetryOptInExtra": "可选遥测数据",
    "overrideHeight": "强制窗口高度",
    "overrideWidth": "强制窗口宽度",
    "fullscreenResolution": "全屏分辨率",
    "hideServerAddress": "隐藏服务器地址",
    "pauseOnLostFocus": "失焦时暂停",
}

#: 认不出来时就用这些前缀去掉再试
_PREFIXES = ("options.", "soundCategory.", "modelPart.")

_SNAKE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _snake(name: str) -> str:
    return _SNAKE_RE.sub("_", name).lower()


def option_candidates(name: str) -> list[str]:
    """给出一个设置项名可能对应的所有翻译键，按可信度排序。"""
    out: list[str] = []
    alias = OPTION_ALIASES.get(name)
    if alias:
        out.append(alias)
    if name.startswith("soundCategory_"):
        out.append("soundCategory." + name[len("soundCategory_"):])
    if name.startswith("modelPart_"):
        out.append("options.modelPart." + name[len("modelPart_"):])
        out.append("options.modelPart_" + name[len("modelPart_"):])
    out.append(f"options.{name}")
    snake = _snake(name)
    if snake != name:
        out.append(f"options.{snake}")
    # 去掉尾部的 tooltip / 修饰词再试一次
    if name.endswith("Mode"):
        out.append(f"options.{name[:-4]}")
    deduped: list[str] = []
    for key in out:
        if key not in deduped:
            deduped.append(key)
    return deduped


# --------------------------------------------------------------------------
# 语言文件定位
# --------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _version_json(version_dir: Path | None) -> dict:
    if version_dir is None or not version_dir.is_dir():
        return {}
    candidates = [version_dir / f"{version_dir.name}.json"]
    candidates += sorted(version_dir.glob("*.json"))
    for path in candidates:
        data = _read_json(path)
        if isinstance(data, dict) and "assetIndex" in data:
            return data
    return {}


def _assets_dir(start: Path | None) -> Path | None:
    """从版本目录一路往上找 assets/（隔离安装时 assets 在父目录）。"""
    if start is None:
        return None
    for base in [start, *start.parents][:6]:
        candidate = base / "assets"
        if (candidate / "objects").is_dir() and (candidate / "indexes").is_dir():
            return candidate
    return None


def find_lang_file(game_dir: Path | None, version_dir: Path | None = None,
                   version_id: str | None = None) -> Path | None:
    """定位原版 zh_cn.json，找不到返回 None。"""
    meta = _version_json(version_dir)
    index_id = None
    ai = meta.get("assetIndex")
    if isinstance(ai, dict):
        index_id = ai.get("id")
    elif isinstance(ai, str):
        index_id = ai

    assets = _assets_dir(version_dir) or _assets_dir(game_dir)
    if assets is None:
        # 旧版本（1.12 及以前）语言文件直接躺在 client jar 里
        return _lang_from_jar(version_dir) or _lang_from_jar(game_dir)

    index = None
    if index_id:
        index = _read_json(assets / "indexes" / f"{index_id}.json")
    if not isinstance(index, dict):
        # 版本 JSON 没写 assetIndex：挑最新改动的索引凑合
        entries = sorted((assets / "indexes").glob("*.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        for path in entries:
            data = _read_json(path)
            if isinstance(data, dict) and LANG_ENTRY in data.get("objects", {}):
                index = data
                break
    if not isinstance(index, dict):
        return None

    entry = index.get("objects", {}).get(LANG_ENTRY)
    if not isinstance(entry, dict):
        return None
    digest = entry.get("hash")
    if not isinstance(digest, str) or len(digest) < 3:
        return None
    obj = assets / "objects" / digest[:2] / digest
    if obj.is_file():
        return obj
    return _lang_from_jar(version_dir) or _lang_from_jar(game_dir)


def _lang_from_jar(directory: Path | None) -> Path | None:
    """1.12 及更早：zh_cn.json 就在 client jar 里。返回 jar 路径。"""
    if directory is None or not directory.is_dir():
        return None
    for jar in sorted(directory.glob("*.jar")):
        try:
            import zipfile

            with zipfile.ZipFile(jar) as zf:
                if "assets/minecraft/lang/zh_cn.json" in zf.namelist():
                    return jar
        except (OSError, Exception):  # zipfile.BadZipFile 等
            continue
    return None


def load_entries(path: Path | None) -> Mapping[str, str]:
    """读出语言条目（带缓存）。path 可以是 json，也可以是含有它的 jar。"""
    if path is None:
        return {}
    try:
        st = path.stat()
    except OSError:
        return {}
    cache_key = (str(path), int(st.st_mtime), st.st_size)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    data: Any = None
    if path.suffix.lower() == ".jar":
        try:
            import zipfile

            with zipfile.ZipFile(path) as zf:
                data = json.loads(
                    zf.read("assets/minecraft/lang/zh_cn.json").decode("utf-8"))
        except Exception:
            data = None
    else:
        data = _read_json(path)

    entries: Mapping[str, str] = data if isinstance(data, dict) else {}
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[cache_key] = entries
    return entries


# --------------------------------------------------------------------------
# 对外对象
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class VanillaLang:
    """一份原版中文语言表。"""

    source: Path | None
    entries: Mapping[str, str]

    #: 解析结果缓存：同一份语言表反复查同样的名字不用重算
    _name_cache: dict[str, str | None] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_name_cache", {})

    def __bool__(self) -> bool:
        return bool(self.entries)

    def text(self, translation_key: str) -> str | None:
        value = self.entries.get(translation_key)
        return value if isinstance(value, str) and value else None

    def key_name(self, translation_key: str) -> str | None:
        """按键的翻译键（`key.sneak`）-> 中文。"""
        if not translation_key.startswith("key."):
            translation_key = "key." + translation_key
        return self.text(translation_key)

    def option_name(self, name: str) -> str | None:
        """`options.txt` 里的设置项名 -> 中文（认不出来返回 None）。"""
        cache = self._name_cache
        if name in cache:
            return cache[name]
        value: str | None = None
        for key in option_candidates(name):
            hit = self.text(key)
            if hit:
                value = hit
                break
        if value is None:
            # 语言文件里没有的，退回手写的少量常用项
            value = OPTION_MANUAL.get(name)
        cache[name] = value
        return value

    def option_display(self, name: str) -> tuple[str, str]:
        """返回 (显示名, 原始英文名)。没有中文时两边都是原始名。"""
        zh = self.option_name(name)
        return (zh, name) if zh else (name, "")


EMPTY = VanillaLang(None, {})


@lru_cache(maxsize=8)
def _load_cached(source: str) -> VanillaLang:
    path = Path(source)
    return VanillaLang(path, load_entries(path))


def for_instance(game_dir: Path | None, version_dir: Path | None = None) -> VanillaLang:
    """给某个实例找一份语言表；找不到返回空的（truthy 判断为 False）。"""
    path = find_lang_file(game_dir, version_dir)
    if path is None:
        return EMPTY
    try:
        return _load_cached(str(path))
    except OSError:
        return EMPTY
