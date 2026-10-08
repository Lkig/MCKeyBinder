# -*- coding: utf-8 -*-
"""应用门面：把各个模块拼成一个「会话」，GUI 与 CLI 共用。

放在这里的东西都是「跨界面共享的状态」：

* 数据目录（配置、备份、缓存）的定位
* 用户设置（手动添加的目录、上次用的配置、同步选项）
* 实例发现 + mod 索引缓存
* 对比表 / 计划的构造入口
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .atomicio import write_text_atomic
from .backups import BackupManager
from .configfiles import ConfigCandidate, scan_config_dir, sync_config_files
from .diff import DiffTable, build_diff
from .instances import Instance, discover
from .mclang import EMPTY as EMPTY_LANG
from .mclang import VanillaLang
from .mclang import for_instance as vanilla_lang_for
from .modscan import ModIndex, ModScanCache
from .naming import NamingResolver
from .optionsfile import DEFAULT_SYNCED_OPTIONS, INSTANCE_SPECIFIC_OPTIONS, OptionsFile
from .profile import Profile, ProfileStore
from .resources import app_dir, resource_dir
from .semantic import SemanticGrouper
from .state import STATE_NAME, SyncState
from .sync import SyncPlan, SyncPolicy, apply_plan, build_plan

ProgressFn = Callable[[str], None]

SETTINGS_NAME = "settings.json"


def default_data_dir() -> Path:
    """数据目录：优先放在程序旁边，不可写时退回用户目录。

    「程序旁边」在 exe 版里指 exe 所在目录（见 ``mcsync/resources.py``），
    而不是 onefile 每次运行都会换的临时解包目录。
    """
    here = app_dir()
    candidate = here / "data"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return candidate
    except OSError:
        fallback = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MCKeyBinder-KeySync"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


@dataclass
class Settings:
    """持久化的用户设置。"""

    manual_game_dirs: list[str] = field(default_factory=list)
    manual_instance_dirs: list[str] = field(default_factory=list)
    last_profile: str = ""
    drive_scan_done: bool = False

    sync_options: bool = False
    option_names: list[str] = field(default_factory=list)
    include_unknown_keybinds: bool = False
    semantic_sync: bool = True
    convert_legacy: bool = True
    skip_unbind: bool = True
    sync_optifine: bool = False
    respect_manual_changes: bool = True
    write_default_targets: bool = False

    selected_instances: list[str] = field(default_factory=list)

    #: 界面状态：窗口尺寸位置、各分栏的拖拽位置、选中的标签页……
    #: 故意做成自由字典，这样加一个新的界面开关不需要动数据结构或迁移旧设置。
    ui: dict = field(default_factory=dict)

    def get_ui(self, key: str, default=None):
        value = self.ui.get(key, default)
        return default if value is None else value

    def set_ui(self, key: str, value) -> None:
        self.ui[key] = value

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class App:
    """一次会话的全部共享状态。"""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.profiles_dir = self.data_dir / "profiles"
        self.backups_dir = self.data_dir / "backups"
        self.cache_dir = self.data_dir / "cache"
        for directory in (self.data_dir, self.profiles_dir,
                          self.backups_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self.settings = self._load_settings()
        self.profile_store = ProfileStore(self.profiles_dir)
        self.backup_manager = BackupManager(self.backups_dir)
        self.semantic = SemanticGrouper.load(self.data_dir / "semantic_overrides.json")

        self.instances: list[Instance] = []
        self.mod_index = ModIndex()
        self._mod_cache = ModScanCache(self.cache_dir / "mods.json")
        self._scanned_instances: set[str] = set()
        self._resolver: NamingResolver | None = None
        self._lang: VanillaLang | None = None
        self._sync_state: SyncState | None = None

    # -- 设置 ------------------------------------------------------------
    def _settings_path(self) -> Path:
        return self.data_dir / SETTINGS_NAME

    def _load_settings(self) -> Settings:
        path = self._settings_path()
        if not path.is_file():
            return Settings()
        try:
            return Settings.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError):
            return Settings()

    def save_settings(self) -> None:
        payload = json.dumps(self.settings.to_dict(), ensure_ascii=False, indent=2)
        write_text_atomic(self._settings_path(), payload, strict=False)

    # -- 同步基线 --------------------------------------------------------
    def sync_state(self) -> SyncState:
        """上次同步留下的基线快照（惰性载入，只读一次）。"""
        if self._sync_state is None:
            self._sync_state = SyncState.load(self.data_dir / STATE_NAME)
        return self._sync_state

    def reset_sync_state(self) -> None:
        """忘掉全部基线：下次同步会把目标的现状当成「未被动过」照常写入。"""
        state = self.sync_state()
        state.clear()
        state.save()

    # -- 实例 ------------------------------------------------------------
    def discover_instances(self, do_drive_scan: bool | None = None,
                           progress: ProgressFn | None = None,
                           cancel: Callable[[], bool] | None = None) -> list[Instance]:
        if do_drive_scan is None:
            do_drive_scan = not self.settings.drive_scan_done
        self.instances = discover(
            extra_game_dirs=[Path(p) for p in self.settings.manual_game_dirs],
            extra_instance_dirs=[Path(p) for p in self.settings.manual_instance_dirs],
            do_drive_scan=do_drive_scan,
            progress=progress,
            cancel=cancel,
        )
        if do_drive_scan:
            self.settings.drive_scan_done = True
            self.save_settings()
        return self.instances

    def add_manual_dir(self, path: Path, as_instance_dir: bool = False) -> None:
        key = "manual_instance_dirs" if as_instance_dir else "manual_game_dirs"
        values: list[str] = getattr(self.settings, key)
        text = str(path)
        if text not in values:
            values.append(text)
            self.save_settings()

    def remove_manual_dir(self, path: Path) -> None:
        text = str(path)
        for key in ("manual_game_dirs", "manual_instance_dirs"):
            values: list[str] = getattr(self.settings, key)
            if text in values:
                values.remove(text)
        self.save_settings()

    # -- mod 索引 --------------------------------------------------------
    def ensure_mod_index(self, instances: Sequence[Instance] | None = None,
                         progress: ProgressFn | None = None,
                         cancel: Callable[[], bool] | None = None,
                         force: bool = False) -> ModIndex:
        """为给定实例建立 mod / 语言索引（带磁盘缓存）。"""
        targets = list(instances if instances is not None else self.instances)
        total = len(targets)
        for index, instance in enumerate(targets, 1):
            if cancel is not None and cancel():
                break
            if not force and instance.key in self._scanned_instances:
                continue
            mods_dir = instance.mods_dir
            if not mods_dir.is_dir():
                self.mod_index.add_instance(instance.key, _empty_scan())
                self._scanned_instances.add(instance.key)
                continue
            if progress is not None:
                progress(f"[{index}/{total}] 扫描 Mod：{instance.name}")

            def sub_progress(done: int, count: int, name: str) -> None:
                if progress is not None and count:
                    progress(f"[{index}/{total}] {instance.name}  {done}/{count}  {name}")

            result = self._mod_cache.scan_dir(mods_dir, progress=sub_progress,
                                              cancel=cancel)
            self.mod_index.add_instance(instance.key, result)
            self._scanned_instances.add(instance.key)

        self._mod_cache.save()
        self._resolver = None
        return self.mod_index

    @property
    def resolver(self) -> NamingResolver:
        if self._resolver is None:
            self._resolver = NamingResolver(self.mod_index, self.semantic)
        return self._resolver

    def vanilla_lang(self, instances: Sequence[Instance] | None = None) -> VanillaLang:
        """原版中文语言表（用来把 options.txt 的英文设置项名翻成中文）。

        它不在 client jar 里，而是按资源索引下载的资源对象；从任意一个实例
        找到一份就够了，找不到就返回空表（``bool()`` 为 False）。
        """
        if self._lang is not None:
            return self._lang
        for instance in (self.instances if instances is None else instances):
            lang = vanilla_lang_for(instance.game_dir, instance.version_dir)
            if lang:
                self._lang = lang
                break
        if self._lang is None:
            self._lang = EMPTY_LANG
        return self._lang

    # -- 配置 ------------------------------------------------------------
    def load_profiles(self) -> list[Profile]:
        return self.profile_store.load_all()

    def save_profile(self, profile: Profile) -> Path:
        path = self.profile_store.save(profile)
        self.settings.last_profile = profile.name
        self.save_settings()
        return path

    def delete_profile(self, name: str) -> bool:
        return self.profile_store.delete(name)

    def capture_profile(self, instance: Instance, name: str,
                        include_options: bool = True) -> Profile:
        """从实例抓取一份配置。"""
        options = OptionsFile.load(instance.options_path)
        option_names = None
        if include_options:
            available = options.non_key_options()
            option_names = [n for n in DEFAULT_SYNCED_OPTIONS if n in available]
            option_names += [n for n in available
                             if n.startswith("soundCategory_")]
        return Profile.capture(options, name=name, source=str(instance.game_dir),
                               include_options=option_names)

    # -- 对比 ------------------------------------------------------------
    def make_diff(self, profile: Profile,
                  instances: Sequence[Instance]) -> DiffTable:
        keybinds_by_instance = {}
        for instance in instances:
            if instance.options_path.is_file():
                keybinds_by_instance[instance.key] = \
                    OptionsFile.load(instance.options_path).keybinds()
            else:
                keybinds_by_instance[instance.key] = {}
        return build_diff(
            profile.keybinds, instances, keybinds_by_instance,
            resolver=self.resolver,
            semantic_sync=self.settings.semantic_sync,
            semantic_grouper=self.semantic,
            name_resolver_instance=instances[0].key if instances else None,
        )

    # -- 同步 ------------------------------------------------------------
    def make_policy(self) -> SyncPolicy:
        return SyncPolicy(
            sync_keybinds=True,
            include_unknown_keybinds=self.settings.include_unknown_keybinds,
            sync_options=self.settings.sync_options,
            option_names=set(self.settings.option_names),
            write_default_targets=self.settings.write_default_targets,
            semantic_sync=self.settings.semantic_sync,
            convert_legacy=self.settings.convert_legacy,
            skip_unbind=self.settings.skip_unbind,
            sync_optifine=self.settings.sync_optifine,
            respect_manual_changes=self.settings.respect_manual_changes,
        )

    def make_plan(self, profile: Profile, instances: Sequence[Instance],
                  selected: dict[str, set[str]] | None = None,
                  progress: ProgressFn | None = None,
                  cancel: Callable[[], bool] | None = None,
                  policy: SyncPolicy | None = None) -> SyncPlan:
        """生成同步计划。

        ``policy`` 用于「只同步按键」/「只同步其他设置」这类**单次**的范围覆盖：
        界面上的同步选项仍然照常保存，但本次计划用传进来的策略，不会被改脏。
        """
        diffs = self.make_diff(profile, instances)
        return build_plan(profile, instances, policy=policy or self.make_policy(),
                          diffs=diffs, selected=selected,
                          resolver=self.resolver, progress=progress,
                          cancel=cancel, state=self.sync_state())

    def run_plan(self, plan: SyncPlan, do_backup: bool = True,
                 force: bool = False,
                 progress: ProgressFn | None = None):
        return apply_plan(plan, backup_manager=self.backup_manager,
                          do_backup=do_backup, force=force, progress=progress,
                          state=self.sync_state())

    # -- 配置文件 --------------------------------------------------------
    def scan_config_files(self, instance: Instance) -> list[ConfigCandidate]:
        return scan_config_dir(instance.game_dir)

    def sync_config_files(self, source: Instance, targets: Sequence[Instance],
                          relative_paths: Sequence[str]):
        return sync_config_files(source.game_dir,
                                 [t.game_dir for t in targets],
                                 relative_paths,
                                 backup_manager=self.backup_manager)


def _empty_scan():
    from .modscan import JarScanResult
    return JarScanResult()
