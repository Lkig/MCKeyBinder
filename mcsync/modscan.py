# -*- coding: utf-8 -*-
"""Mod 扫描：从整合包的 ``mods/`` 目录里读出 mod 列表与按键的显示名。

做两件事：

1. **mod 清单**：读 jar 里的 ``fabric.mod.json`` / ``META-INF/neoforge.mods.toml`` /
   ``META-INF/mods.toml`` / ``quilt.mod.json``，拿到 modid、显示名、版本。
   **必须递归进嵌套 jar**（``META-INF/jarjar/*.jar``、``META-INF/jars/*.jar``）——
   实测 185 个 jar 里有相当一部分 mod（如 Create 的 ``ponder``、``l2core``）是
   jar-in-jar 打包的，不递归就会漏掉，导致按键名解析不出来。

2. **按键显示名**：mod 的语言文件里，按键的翻译键就是 options.txt 里去掉 ``key_``
   前缀后的那串（``key_key.jei.showRecipe`` -> ``key.jei.showRecipe``；
   ``key_gui.xaero_open_map`` -> ``gui.xaero_open_map``）。
   注意命名空间**完全不规则**：Iris 用 ``key_iris.…``、Xaero 用 ``key_gui.xaero_…``、
   Create 用 ``key_create.…``、fxntstorage 用 ``key_hotKey.…``，
   所以不能靠「前缀 = modid」来猜，必须老老实实查语言文件。
"""

from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

from .atomicio import write_text_atomic

ProgressFn = Callable[[int, int, str], None]

#: 语言文件优先级：中文优先，其次英文
LANG_PRIORITY: dict[str, int] = {
    "zh_cn": 40,
    "zh_tw": 35,
    "zh_hk": 34,
    "en_us": 30,
    "en_gb": 28,
}

_LANG_JSON_RE = re.compile(r"(?:^|/)lang/([a-zA-Z_]{2,10}(?:_[a-zA-Z]{2,4})?)\.json$")
_LANG_PROPS_RE = re.compile(r"(?:^|/)lang/([a-zA-Z_]{2,10}(?:_[a-zA-Z]{2,4})?)\.lang$")
_NAMESPACE_RE = re.compile(r"(?:^|/)assets/([^/]+)/lang/")
_NESTED_JAR_RE = re.compile(r"^META-INF/(?:jarjar|jars|versions)/.*\.jar$")


def _namespace_of(lang_path: str) -> str:
    """从 ``assets/<namespace>/lang/xx_xx.json`` 里取出资源命名空间。"""
    m = _NAMESPACE_RE.search(lang_path)
    return m.group(1) if m else ""

#: 依次尝试的 mod 元数据文件
_MOD_META_FILES = (
    "fabric.mod.json",
    "quilt.mod.json",
    "META-INF/neoforge.mods.toml",
    "META-INF/mods.toml",
    "mcmod.info",
)


@dataclass
class ModInfo:
    mod_id: str
    name: str
    version: str = ""
    loader: str = ""
    jar: str = ""
    nested_in: str = ""

    @property
    def label(self) -> str:
        return self.name or self.mod_id


@dataclass
class LangEntry:
    text: str
    mod_id: str
    jar: str
    priority: int


class JarScanResult:
    """单个 jar（含其嵌套 jar）的扫描结果。"""

    __slots__ = ("mods", "lang", "categories")

    def __init__(self) -> None:
        self.mods: list[ModInfo] = []
        self.lang: dict[str, LangEntry] = {}
        self.categories: dict[str, LangEntry] = {}


# --------------------------------------------------------------------------
# 单 jar 扫描
# --------------------------------------------------------------------------

def _read_toml_string(text: str, key: str) -> str:
    m = re.search(rf'^\s*{key}\s*=\s*"([^"]*)"', text, re.MULTILINE)
    return m.group(1) if m else ""


def _parse_mod_metadata(zf: zipfile.ZipFile, names: Sequence[str],
                        jar_name: str, nested_in: str) -> list[ModInfo]:
    """从一个已打开的 zip 里读出所有 mod 声明。"""
    out: list[ModInfo] = []

    for meta in _MOD_META_FILES:
        if meta not in names:
            continue
        try:
            raw = zf.read(meta).decode("utf-8", errors="replace")
        except (KeyError, OSError):
            continue

        if meta == "fabric.mod.json":
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mod_id = data.get("id") or ""
            if mod_id:
                out.append(ModInfo(
                    mod_id=mod_id,
                    name=data.get("name") or mod_id,
                    version=str(data.get("version") or ""),
                    loader="fabric",
                    jar=jar_name,
                    nested_in=nested_in,
                ))
        elif meta == "quilt.mod.json":
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            qmod = (data.get("quilt_loader") or {}).get("metadata") or {}
            mod_id = (data.get("quilt_loader") or {}).get("id") or ""
            if mod_id:
                out.append(ModInfo(
                    mod_id=mod_id,
                    name=qmod.get("name") or mod_id,
                    version=str((data.get("quilt_loader") or {}).get("version") or ""),
                    loader="quilt",
                    jar=jar_name,
                    nested_in=nested_in,
                ))
        elif meta in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
            loader = "neoforge" if "neoforge" in meta else "forge"
            # [[mods]] 段落；一个文件可能声明多个 mod
            blocks = re.split(r"\[\[mods\]\]", raw)[1:]
            for block in blocks:
                mod_id = _read_toml_string(block, "modId")
                if not mod_id:
                    continue
                out.append(ModInfo(
                    mod_id=mod_id,
                    name=_read_toml_string(block, "displayName") or mod_id,
                    version=_read_toml_string(block, "version"),
                    loader=loader,
                    jar=jar_name,
                    nested_in=nested_in,
                ))
        elif meta == "mcmod.info":
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, list):
                for item in data:
                    mod_id = item.get("modid") or ""
                    if mod_id:
                        out.append(ModInfo(mod_id=mod_id,
                                           name=item.get("name") or mod_id,
                                           version=str(item.get("version") or ""),
                                           loader="forge", jar=jar_name,
                                           nested_in=nested_in))
        if out:
            break

    return out


def _merge_lang(target: dict[str, LangEntry], src: dict[str, LangEntry]) -> None:
    for key, entry in src.items():
        old = target.get(key)
        if old is None or entry.priority > old.priority:
            target[key] = entry


def _scan_zip(blob: bytes | Path, jar_name: str, result: JarScanResult,
              nested_in: str = "", depth: int = 0) -> None:
    """扫描一个 jar（可来自路径或内存字节）。

    ``depth`` 限制嵌套层数，避免病态 jar 无限递归。
    """
    if depth > 3:
        return
    if isinstance(blob, (bytes, bytearray, memoryview)):
        # zipfile 只接受路径或文件对象，bytes 必须包一层
        blob = io.BytesIO(blob)
    try:
        zf = zipfile.ZipFile(blob)
    except (zipfile.BadZipFile, OSError, ValueError):
        return

    with zf:
        names = zf.namelist()
        name_set = set(names)

        for mod in _parse_mod_metadata(zf, names, jar_name, nested_in):
            result.mods.append(mod)

        declared_ids = {m.mod_id for m in result.mods}

        # 语言文件
        for name in names:
            m = _LANG_JSON_RE.search(name)
            props = False
            if not m:
                m = _LANG_PROPS_RE.search(name)
                props = bool(m)
            if not m:
                continue
            locale = m.group(1).lower()
            priority = LANG_PRIORITY.get(locale)
            if priority is None:
                continue
            try:
                raw = zf.read(name).decode("utf-8", errors="replace")
            except (KeyError, OSError):
                continue
            entries = _parse_lang_props(raw) if props else _parse_lang_json(raw)
            if not entries:
                continue
            # 语言文件的资源命名空间（assets/<namespace>/lang/...）通常就是 modid。
            # 优先用它，拿不到再退回到「这个 jar 声明的唯一 mod」。
            namespace = _namespace_of(name)
            if namespace in declared_ids:
                mod_id = namespace
            elif len(declared_ids) == 1:
                mod_id = next(iter(declared_ids))
            else:
                mod_id = namespace or ""
            for key, text in entries:
                entry = LangEntry(text=text, mod_id=mod_id, jar=jar_name,
                                  priority=priority)
                if key.startswith("key.categories."):
                    old = result.categories.get(key)
                    if old is None or priority > old.priority:
                        result.categories[key] = entry
                else:
                    old = result.lang.get(key)
                    if old is None or priority > old.priority:
                        result.lang[key] = entry

        # 递归嵌套 jar
        for name in names:
            if not _NESTED_JAR_RE.match(name):
                continue
            try:
                nested_blob = zf.read(name)
            except (KeyError, OSError):
                continue
            _scan_zip(nested_blob, os.path.basename(name), result,
                      nested_in=jar_name, depth=depth + 1)


def _parse_lang_json(raw: str) -> Iterator[tuple[str, str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if isinstance(value, str):
            yield key, value


def _parse_lang_props(raw: str) -> Iterator[tuple[str, str]]:
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        yield key.strip(), value.strip()


# --------------------------------------------------------------------------
# mods 目录扫描
# --------------------------------------------------------------------------

def list_mod_jars(mods_dir: Path) -> list[Path]:
    """列出 mods 目录里的 jar（包含被禁用的 ``.jar.disabled``）。"""
    if not mods_dir.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(mods_dir.iterdir()):
        if not entry.is_file():
            continue
        lower = entry.name.lower()
        if lower.endswith(".jar") or lower.endswith(".jar.disabled") \
                or lower.endswith(".zip"):
            out.append(entry)
    return out


def scan_mods_dir(mods_dir: Path, progress: ProgressFn | None = None,
                  cancel: Callable[[], bool] | None = None) -> JarScanResult:
    """扫描整个 mods 目录。"""
    result = JarScanResult()
    jars = list_mod_jars(mods_dir)
    total = len(jars)
    for i, jar in enumerate(jars, 1):
        if cancel is not None and cancel():
            break
        if progress is not None:
            progress(i, total, jar.name)
        _scan_zip(jar, jar.name, result)
    return result


# --------------------------------------------------------------------------
# 全局索引（跨实例取并集）
# --------------------------------------------------------------------------

_CLEAN_RE = re.compile(r"[^a-z0-9]")
_SPLIT_RE = re.compile(r"[._\-/]")
# 这些片段在翻译键里到处都是，拿它们猜归属一定会张冠李戴
_OWNER_NOISE = frozenset({
    "key", "keys", "gui", "hotkey", "info", "desc",
    "category", "open", "toggle", "config", "settings",
})


def _clean_token(text: str) -> str:
    return _CLEAN_RE.sub("", text)


class ModIndex:
    """多个实例的 mod 与语言信息并集。

    之所以要跨实例取并集：这样即使某个目标实例没有装某个 mod，
    界面里依然能显示该按键的中文名，而不是一串天书。
    """

    def __init__(self) -> None:
        self.mods: dict[str, ModInfo] = {}
        self.lang: dict[str, LangEntry] = {}
        self.categories: dict[str, LangEntry] = {}
        self._mods_by_instance: dict[str, set[str]] = {}
        # modid → 去掉非字母数字后的形式，guess_owner 会反复用到
        self._norm_by_mod: dict[str, str] = {}

    # -- 构建 ------------------------------------------------------------
    def add_instance(self, instance_key: str, result: JarScanResult) -> None:
        ids: set[str] = set()
        for mod in result.mods:
            ids.add(mod.mod_id)
            self.mods.setdefault(mod.mod_id, mod)
        self._mods_by_instance[instance_key] = ids
        _merge_lang(self.lang, result.lang)
        _merge_lang(self.categories, result.categories)

    def instance_mod_ids(self, instance_key: str) -> set[str]:
        return self._mods_by_instance.get(instance_key, set())

    # -- 查询 ------------------------------------------------------------
    def display_name(self, translation_key: str) -> str | None:
        entry = self.lang.get(translation_key)
        return entry.text if entry else None

    def owner_mod(self, translation_key: str) -> str | None:
        entry = self.lang.get(translation_key)
        return entry.mod_id if entry and entry.mod_id else None

    def category_name(self, category_key: str) -> str | None:
        entry = self.categories.get(category_key)
        return entry.text if entry else None

    def guess_owner(self, translation_key: str,
                    candidates: Iterable[str] | None = None) -> str | None:
        """语言文件里查不到时，用名字片段猜归属 mod。

        处理 ``key.l2mods.dig`` 这类「翻译键前缀 ≠ modid」或语言文件缺失的情况。
        用**打分**而不是「命中即返回」，因为粗略匹配很容易张冠李戴：
        例如 ``key.irons_spellbooks.spell_wheel`` 里的 ``irons`` 同时是
        ``irons_jewelry`` 和 ``irons_spellbooks`` 的前缀，只有 ``spellbooks``
        这一段能唯一定位。因此必须取**最长的匹配片段**，且要求它明显优于次优解。
        """
        pool = list(candidates) if candidates is not None else list(self.mods)
        if not pool:
            return None

        tokens = [t for t in _SPLIT_RE.split(translation_key.lower())
                  if len(t) >= 3 and t not in _OWNER_NOISE]
        # 令牌的归一化只跟 translation_key 有关，先算一次；以前放在 mod 循环里，
        # 四百个 mod × 两三个令牌就是上千次正则替换。
        clean_tokens = [t for t in (_clean_token(t) for t in tokens) if len(t) >= 3]
        if not clean_tokens:
            return None

        norm = self._norm_by_mod
        best_mod: str | None = None
        best_score = 0
        second_score = 0

        for mod_id in pool:
            mid = norm.get(mod_id)
            if mid is None:
                mid = _clean_token(mod_id.lower())
                norm[mod_id] = mid
            if not mid:
                continue
            score = 0
            for tok in clean_tokens:
                if tok == mid:
                    score = max(score, 1000 + len(tok))
                elif len(tok) >= 5 and tok in mid:
                    score = max(score, len(tok))
                elif len(tok) >= 5 and mid in tok:
                    score = max(score, len(mid))
            if score > best_score:
                second_score = best_score
                best_score = score
                best_mod = mod_id
            elif score > second_score:
                second_score = score

        # 必须唯一胜出，且领先明显，避免把相近的 mod 认错
        if best_mod is None or best_score < 5:
            return None
        if best_score < 1000 and best_score <= second_score:
            return None
        return best_mod


# --------------------------------------------------------------------------
# 磁盘缓存
# --------------------------------------------------------------------------

_CACHE_VERSION = 3


class ModScanCache:
    """按 (路径, mtime, size) 缓存每个 jar 的扫描结果。

    185 个 jar + 嵌套 jar 全量扫描大约要几秒；缓存后第二次打开是毫秒级。
    """

    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path
        self._data: dict[str, dict] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if raw.get("version") != _CACHE_VERSION:
            return
        self._data = raw.get("jars", {})

    def save(self) -> None:
        if not self._dirty:
            return
        payload = {"version": _CACHE_VERSION, "jars": self._data}
        # 缓存丢了只是下次重扫，别让写失败冒到界面上。
        write_text_atomic(self.cache_path,
                          json.dumps(payload, ensure_ascii=False),
                          strict=False)

    @staticmethod
    def _stamp(jar: Path) -> str:
        try:
            st = jar.stat()
        except OSError:
            return "0:0"
        return f"{int(st.st_mtime)}:{st.st_size}"

    def scan_dir(self, mods_dir: Path, progress: ProgressFn | None = None,
                 cancel: Callable[[], bool] | None = None) -> JarScanResult:
        result = JarScanResult()
        jars = list_mod_jars(mods_dir)
        total = len(jars)
        for i, jar in enumerate(jars, 1):
            if cancel is not None and cancel():
                break
            if progress is not None:
                progress(i, total, jar.name)

            key = str(jar.resolve()).lower()
            stamp = self._stamp(jar)
            cached = self._data.get(key)
            if cached and cached.get("stamp") == stamp:
                self._apply_cached(result, cached)
                continue

            single = JarScanResult()
            _scan_zip(jar, jar.name, single)
            self._data[key] = self._freeze(single, stamp)
            self._dirty = True
            _merge_lang(result.lang, single.lang)
            _merge_lang(result.categories, single.categories)
            result.mods.extend(single.mods)
        return result

    @staticmethod
    def _freeze(single: JarScanResult, stamp: str) -> dict:
        return {
            "stamp": stamp,
            "mods": [asdict(m) for m in single.mods],
            "lang": {k: [v.text, v.mod_id, v.priority] for k, v in single.lang.items()},
            "categories": {k: [v.text, v.mod_id, v.priority] for k, v in single.categories.items()},
        }

    @staticmethod
    def _apply_cached(result: JarScanResult, cached: dict) -> None:
        for m in cached.get("mods", []):
            result.mods.append(ModInfo(**m))
        for k, v in cached.get("lang", {}).items():
            entry = LangEntry(text=v[0], mod_id=v[1], jar="", priority=v[2])
            old = result.lang.get(k)
            if old is None or entry.priority > old.priority:
                result.lang[k] = entry
        for k, v in cached.get("categories", {}).items():
            entry = LangEntry(text=v[0], mod_id=v[1], jar="", priority=v[2])
            old = result.categories.get(k)
            if old is None or entry.priority > old.priority:
                result.categories[k] = entry
