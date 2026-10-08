# -*- coding: utf-8 -*-
"""实例发现：找出机器上所有可同步的 Minecraft 整合包 / 实例。

覆盖的启动器（Windows）：

============  ==========================================================
PCL2          从 ``PCL/config.v1.yml`` 的 ``LaunchFolderSelect`` 读游戏目录
              （``$`` 表示 PCL 程序所在目录），再扫 ``versions/``
HMCL          默认 ``%APPDATA%\\.minecraft``，同样扫 ``versions/``
官方启动器    ``%APPDATA%\\.minecraft``
Prism/MultiMC ``instances/<名字>/.minecraft/``，靠 ``instance.cfg`` 识别
CurseForge    ``%USERPROFILE%\\curseforge\\minecraft\\Instances\\<名字>\\``
Modrinth App  ``%APPDATA%\\com.modrinth.theseus\\profiles\\<名字>\\``
ATLauncher    ``%APPDATA%\\ATLauncher\\instances\\<名字>\\``
GDLauncher    ``%APPDATA%\\gdlauncher_next\\instances\\<名字>\\``
============  ==========================================================

除了预设路径，还提供**有界磁盘扫描**：只找名为 ``.minecraft`` / ``minecraft``
且含 ``versions`` 或 ``mods`` 的目录，深度受限并跳过系统目录。PCL2 装在自定义
路径（如 ``D:\\Games\\PCL2``）时就是靠这一步找到的。
"""

from __future__ import annotations

import json
import os
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

ProgressFn = Callable[[str], None]

#: 版本号形如 1.21.1 / 1.12.2 / 1.20
_MC_VERSION_RE = re.compile(r"\b(1\.\d{1,2}(?:\.\d{1,2})?)\b")

#: 扫描时跳过的目录名（小写比较）
SKIP_DIRS: frozenset[str] = frozenset({
    "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "$winreagent", "recovery",
    "perflogs", "msocache", "node_modules", ".git", ".svn", "__pycache__",
    "site-packages", "appdata", "application data", "documents and settings",
    "venv", ".venv", "env", "temp", "tmp", "cache", "packages",
    "comfyui_windows_portable", "dlls", "winsxs", "installer",
    "assembly", "microsoft", "nvidia", "amd", "intel",
})

#: 识别为游戏目录的条件：这些文件名之一存在
_GAME_ROOT_MARKERS = ("options.txt", "launcher_profiles.json", "mods", "saves",
                      "resourcepacks", "shaderpacks", "config")

#: 各启动器的默认实例目录
DEFAULT_INSTANCE_DIRS: tuple[tuple[str, str], ...] = (
    ("Prism Launcher", r"%APPDATA%\PrismLauncher\instances"),
    ("MultiMC", r"%APPDATA%\MultiMC\instances"),
    ("PolyMC", r"%APPDATA%\PolyMC\instances"),
    ("CurseForge", r"%USERPROFILE%\curseforge\minecraft\Instances"),
    # Modrinth App 0.8.0 起目录名从 com.modrinth.theseus 改成 ModrinthApp
    ("Modrinth App", r"%APPDATA%\ModrinthApp\profiles"),
    ("Modrinth App (旧版)", r"%APPDATA%\com.modrinth.theseus\profiles"),
    ("ATLauncher", r"%APPDATA%\ATLauncher\instances"),
    ("ATLauncher (备用)", r"%APPDATA%\.ATLauncher\instances"),
    # GDLauncher Carbon
    ("GDLauncher", r"%APPDATA%\gdlauncher_carbon\data\instances"),
    ("GDLauncher (旧版)", r"%APPDATA%\gdlauncher_next\instances"),
    ("GDLauncher (更旧)", r"%APPDATA%\.gdlauncher\instances"),
)

#: 可能是游戏根目录的默认候选
DEFAULT_GAME_DIRS: tuple[tuple[str, str], ...] = (
    ("官方启动器 / HMCL", r"%APPDATA%\.minecraft"),
    ("官方启动器", r"%USERPROFILE%\.minecraft"),
)


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------

@dataclass
class Instance:
    """一个可同步的整合包 / 实例。"""

    name: str
    game_dir: Path
    launcher: str
    options_path: Path
    mc_version: str | None = None
    loader: str | None = None
    version_dir: Path | None = None
    origin: str = ""
    exists: bool = True

    #: 额外的「默认值」文件：configureddefaults / defaultoptions / kubejs 等。
    #: 写这些文件可以让你**换新整合包、或整合包更新重置设置后**仍然是你的键位。
    default_targets: list[Path] = field(default_factory=list)

    @property
    def key(self) -> str:
        return str(self.options_path.resolve()).lower()

    @property
    def mods_dir(self) -> Path:
        return self.game_dir / "mods"

    @property
    def optifine_path(self) -> Path:
        """OptiFine 的设置文件。它**也存按键**（``key_of.key.zoom:46``），
        而且是旧式数字键码，所以单独处理而不是塞进 default_targets。"""
        return self.game_dir / "optionsof.txt"

    @property
    def has_optifine(self) -> bool:
        return self.optifine_path.is_file()

    @property
    def version_label(self) -> str:
        parts = [p for p in (self.mc_version, self.loader) if p]
        return " / ".join(parts) if parts else "未知版本"

    @property
    def title(self) -> str:
        return f"{self.name}  ({self.version_label})"

    @property
    def subtitle(self) -> str:
        return str(self.game_dir)


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def _expand(template: str) -> Path:
    """展开 ``%APPDATA%`` 这类环境变量。"""
    return Path(os.path.expandvars(template))


def looks_like_game_root(path: Path) -> bool:
    """判断一个目录是不是 Minecraft 游戏目录（``.minecraft``）。"""
    if not path.is_dir():
        return False
    name = path.name.lower()
    has_versions = (path / "versions").is_dir()
    marker_count = sum(1 for m in _GAME_ROOT_MARKERS if (path / m).exists())

    if name in (".minecraft", "minecraft"):
        return has_versions or marker_count >= 1
    # 名字不叫 .minecraft，但结构很像（Prism 的 .minecraft 子目录会走到这里）
    return has_versions and marker_count >= 2


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None


def detect_loader(libs: Iterable[str]) -> str | None:
    """从版本 JSON 的 libraries 里判断加载器。"""
    text = "\n".join(libs).lower()
    if "net.neoforged:neoforge" in text or "net.neoforged.fancymodloader" in text:
        return "NeoForge"
    if "net.minecraftforge:forge" in text:
        return "Forge"
    if "net.fabricmc:fabric-loader" in text:
        return "Fabric"
    if "org.quiltmc:quilt-loader" in text:
        return "Quilt"
    if "net.fabricmc" in text:
        return "Fabric"
    if "net.minecraftforge" in text:
        return "Forge"
    return None


def loader_from_mods(mods_dir: Path) -> str | None:
    """版本 JSON 看不出加载器时，用 mods 目录里的 jar 猜。"""
    from .modscan import list_mod_jars, _MOD_META_FILES
    import zipfile

    jars = list_mod_jars(mods_dir)
    if not jars:
        return None
    counts = {"fabric": 0, "neoforge": 0, "forge": 0, "quilt": 0}
    for jar in jars[:40]:
        try:
            with zipfile.ZipFile(jar) as zf:
                names = set(zf.namelist())
        except (zipfile.BadZipFile, OSError):
            continue
        if "fabric.mod.json" in names:
            counts["fabric"] += 1
        elif "quilt.mod.json" in names:
            counts["quilt"] += 1
        elif "META-INF/neoforge.mods.toml" in names:
            counts["neoforge"] += 1
        elif "META-INF/mods.toml" in names:
            counts["forge"] += 1
    best = max(counts, key=lambda k: counts[k])
    if counts[best] == 0:
        return None
    return {"fabric": "Fabric", "neoforge": "NeoForge",
            "forge": "Forge", "quilt": "Quilt"}[best]


def _version_meta(version_dir: Path) -> tuple[str | None, str | None]:
    """从 ``versions/<名字>/<名字>.json`` 读出 (MC 版本, 加载器)。"""
    if not version_dir.is_dir():
        return None, None
    candidates = [version_dir / f"{version_dir.name}.json"]
    candidates += sorted(version_dir.glob("*.json"))
    for cand in candidates:
        if not cand.is_file():
            continue
        data = _read_json(cand)
        if not data or "libraries" not in data:
            continue
        mc = data.get("clientVersion") or data.get("inheritsFrom")
        if not mc:
            m = _MC_VERSION_RE.search(version_dir.name)
            mc = m.group(1) if m else None
        loader = detect_loader(
            lib.get("name", "") for lib in data.get("libraries", []))
        return mc, loader
    m = _MC_VERSION_RE.search(version_dir.name)
    return (m.group(1) if m else None), None


def _find_default_targets(game_dir: Path) -> list[Path]:
    """找出该实例里的「默认值」文件（可选的附加写入目标）。"""
    out: list[Path] = []
    candidates = (
        game_dir / "configureddefaults" / "options.txt",   # Configured Defaults
        game_dir / "config" / "defaultoptions" / "options.txt",  # Default Options
        game_dir / "config" / "defaultoptions" / "keybindings.txt",
        game_dir / "kubejs" / "config" / "defaultoptions.txt",   # KubeJS
    )
    for cand in candidates:
        if cand.is_file():
            out.append(cand)
    return out


def _make_instance(name: str, game_dir: Path, launcher: str,
                   options_path: Path | None = None,
                   version_dir: Path | None = None,
                   origin: str = "") -> Instance:
    if options_path is None:
        options_path = game_dir / "options.txt"
    if version_dir is not None:
        mc, loader = _version_meta(version_dir)
    else:
        mc, loader = None, None
    if mc is None:
        m = _MC_VERSION_RE.search(name)
        mc = m.group(1) if m else None
    return Instance(
        name=name,
        game_dir=game_dir,
        launcher=launcher,
        options_path=options_path,
        mc_version=mc,
        loader=loader,
        version_dir=version_dir,
        origin=origin,
        exists=options_path.is_file(),
        default_targets=_find_default_targets(game_dir),
    )


# --------------------------------------------------------------------------
# 扫描一个游戏目录
# --------------------------------------------------------------------------

def scan_game_dir(game_dir: Path, launcher: str,
                  progress: ProgressFn | None = None) -> list[Instance]:
    """扫描一个 ``.minecraft`` 目录，返回其中的所有实例。

    * 有 ``versions/<名字>/`` 的按版本隔离处理，每个版本一个实例。
    * 同时把根目录本身的 ``options.txt`` 也作为一个实例（版本隔离关闭时用）。
    """
    out: list[Instance] = []
    if not game_dir.is_dir():
        return out

    versions_dir = game_dir / "versions"
    if versions_dir.is_dir():
        for version_dir in sorted(versions_dir.iterdir()):
            if not version_dir.is_dir():
                continue
            # 只认有版本 JSON 的目录，避免把乱七八糟的文件夹当实例
            if not any(version_dir.glob("*.json")):
                continue
            if progress is not None:
                progress(f"发现实例：{version_dir.name}")
            out.append(_make_instance(
                name=version_dir.name,
                game_dir=version_dir,
                launcher=launcher,
                options_path=version_dir / "options.txt",
                version_dir=version_dir,
                origin=f"{launcher} · 版本隔离",
            ))

    # 根目录自身的 options.txt（版本隔离关闭的整合包会写在这里）
    root_options = game_dir / "options.txt"
    if root_options.is_file():
        if progress is not None:
            progress(f"发现实例：{game_dir.name}（根目录）")
        out.append(_make_instance(
            name=f"{game_dir.name}（未隔离）",
            game_dir=game_dir,
            launcher=launcher,
            options_path=root_options,
            origin=f"{launcher} · 根目录",
        ))

    return out


def scan_instances_dir(instances_dir: Path, launcher: str,
                       progress: ProgressFn | None = None) -> list[Instance]:
    """扫描 Prism / CurseForge 这类「一个子目录一个实例」的目录。"""
    out: list[Instance] = []
    if not instances_dir.is_dir():
        return out
    for entry in sorted(instances_dir.iterdir()):
        if not entry.is_dir():
            continue
        # Prism / MultiMC 的游戏目录可能是 minecraft/ 也可能是 .minecraft/，
        # 两者都存在时优先 minecraft/（与 Prism 源码 gameRoot() 的判定一致）。
        candidates = [entry / "minecraft", entry / ".minecraft", entry]
        game_dir = next((c for c in candidates if c.is_dir()), entry)
        if not looks_like_game_root(game_dir) and not looks_like_game_root(entry):
            continue
        if progress is not None:
            progress(f"发现实例：{entry.name}")
        out.append(_make_instance(
            name=entry.name,
            game_dir=game_dir,
            launcher=launcher,
            options_path=game_dir / "options.txt",
            origin=f"{launcher} · {instances_dir}",
        ))
    return out


# --------------------------------------------------------------------------
# PCL2
# --------------------------------------------------------------------------

def find_pcl2_dirs(extra_search_roots: Sequence[Path] = ()) -> list[Path]:
    """找出 PCL2 程序目录（含 ``PCL/config.v1.yml`` 的目录）。"""
    found: list[Path] = []

    def consider(path: Path) -> None:
        if path in found:
            return
        found.append(path)

    # 常见安装位置
    candidates: list[Path] = []
    for base in (Path.home() / "Desktop", Path.home() / "Documents",
                 Path.home() / "Downloads", Path("C:/"), Path("D:/"),
                 Path("E:/")):
        if not base.is_dir():
            continue
        try:
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                if "pcl" in child.name.lower():
                    candidates.append(child)
        except (OSError, PermissionError):
            continue

    candidates.extend(extra_search_roots)

    for cand in candidates:
        try:
            if (cand / "PCL" / "config.v1.yml").is_file():
                consider(cand)
        except OSError:
            continue
    return found


def pcl2_game_dirs(extra_search_roots: Sequence[Path] = ()) -> list[Path]:
    """从 PCL2 配置里读出它当前使用的游戏目录。"""
    out: list[Path] = []
    for pcl_root in find_pcl2_dirs(extra_search_roots):
        cfg = pcl_root / "PCL" / "config.v1.yml"
        try:
            text = cfg.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"^LaunchFolderSelect:\s*(.+)$", text, re.MULTILINE)
        if not m:
            continue
        raw = m.group(1).strip()
        # PCL 用 $ 表示程序所在目录
        if raw.startswith("$"):
            raw = raw[1:].lstrip("\\/")
            candidate = (pcl_root / raw) if raw else pcl_root
        else:
            candidate = Path(raw)
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_dir():
            out.append(resolved)
    return out


# --------------------------------------------------------------------------
# 有界磁盘扫描
# --------------------------------------------------------------------------

def bounded_scan(roots: Sequence[Path], max_depth: int = 4,
                 progress: ProgressFn | None = None,
                 cancel: Callable[[], bool] | None = None) -> list[Path]:
    """在指定根目录下有限深度地找 Minecraft 游戏目录。"""
    results: list[Path] = []
    seen: set[str] = set()

    def walk(directory: Path, depth: int) -> None:
        if cancel is not None and cancel():
            return
        if depth > max_depth:
            return
        try:
            entries = list(directory.iterdir())
        except (OSError, PermissionError):
            return

        for entry in entries:
            if cancel is not None and cancel():
                return
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                continue

            lower = entry.name.lower()
            if lower in SKIP_DIRS or lower.startswith("$"):
                continue

            try:
                key = str(entry.resolve()).lower()
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)

            if looks_like_game_root(entry):
                if progress is not None:
                    progress(f"找到游戏目录：{entry}")
                results.append(entry)
                # 找到 .minecraft 后不再往里钻
                continue

            walk(entry, depth + 1)

    for root in roots:
        if root.is_dir():
            walk(root, 0)
    return results


def available_drive_roots() -> list[Path]:
    """返回所有可扫描的盘符根目录。"""
    out: list[Path] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:/")
        try:
            if root.is_dir():
                out.append(root)
        except OSError:
            continue
    return out


# --------------------------------------------------------------------------
# 总入口
# --------------------------------------------------------------------------

def discover(extra_game_dirs: Sequence[Path] = (),
             extra_instance_dirs: Sequence[Path] = (),
             do_drive_scan: bool = True,
             scan_roots: Sequence[Path] | None = None,
             progress: ProgressFn | None = None,
             cancel: Callable[[], bool] | None = None) -> list[Instance]:
    """发现所有实例。

    ``extra_game_dirs`` / ``extra_instance_dirs`` 是用户手动添加的目录。
    """
    instances: list[Instance] = []
    seen_options: set[str] = set()

    def add_all(new: Iterable[Instance]) -> None:
        for inst in new:
            k = inst.key
            if k in seen_options:
                continue
            seen_options.add(k)
            instances.append(inst)

    def note(msg: str) -> None:
        if progress is not None:
            progress(msg)

    # 1) 用户手动添加
    for path in extra_game_dirs:
        note(f"扫描手动添加的游戏目录 {path}")
        add_all(_scan_any(path, "手动添加", progress))

    # 2) 启动器默认路径
    for launcher, template in DEFAULT_GAME_DIRS:
        path = _expand(template)
        if looks_like_game_root(path):
            note(f"扫描 {launcher}：{path}")
            add_all(scan_game_dir(path, launcher, progress))

    for launcher, template in DEFAULT_INSTANCE_DIRS:
        path = _expand(template)
        if path.is_dir():
            note(f"扫描 {launcher}：{path}")
            add_all(scan_instances_dir(path, launcher, progress))

    for path in extra_instance_dirs:
        note(f"扫描手动添加的实例目录 {path}")
        add_all(scan_instances_dir(path, "手动添加", progress))

    # 3) PCL2：读它的配置拿到当前游戏目录
    for path in pcl2_game_dirs(extra_game_dirs):
        note(f"扫描 PCL2 游戏目录：{path}")
        add_all(scan_game_dir(path, "PCL2", progress))

    # 4) 有界磁盘扫描兜底
    if do_drive_scan:
        roots = list(scan_roots) if scan_roots else available_drive_roots()
        note(f"开始扫描磁盘（{', '.join(str(r) for r in roots)}）……")
        for game_dir in bounded_scan(roots, progress=progress, cancel=cancel):
            # 已经在别处登记过就跳过
            if any(str(game_dir).lower() == str(i.game_dir).lower()
                   for i in instances):
                continue
            launcher = "PCL2" if (game_dir / "PCL.ini").is_file() else "磁盘扫描"
            note(f"扫描 {game_dir}")
            add_all(scan_game_dir(game_dir, launcher, progress))

    return instances


def _scan_any(path: Path, launcher: str,
              progress: ProgressFn | None = None) -> list[Instance]:
    """尽最大努力把一个用户给的目录解释成实例集合。"""
    if not path.is_dir():
        return []
    if path.name.lower() == "versions":
        return scan_game_dir(path.parent, launcher, progress)
    if (path / "instance.cfg").is_file() or (path / ".minecraft").is_dir():
        return scan_instances_dir(path.parent, launcher, progress)
    if looks_like_game_root(path):
        return scan_game_dir(path, launcher, progress)
    # 兜底：递归两层的实例目录
    out = scan_instances_dir(path, launcher, progress)
    if not out:
        out = scan_game_dir(path, launcher, progress)
    return out
