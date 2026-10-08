# -*- coding: utf-8 -*-
"""备份与还原。

写入 ``options.txt`` 之前一律先备份。理由（调研里踩过的坑）：

* Minecraft 退出时会**整份重写** options.txt，只保留「自己认识的值」，
  所以一次错误的同步可能让某个整合包的键位被静默抹掉。
* 部分启动器 / 整合包更新会重置 options.txt（国产 Mod ``Options Rewriter``
  存在的唯一理由就是对抗这件事）。

备份目录结构::

    <数据目录>/backups/20260917-123456_同步前/
        manifest.json
        files/
            <序号>_<原始文件名>
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_NAME = "manifest.json"


@dataclass
class BackupEntry:
    """备份里的一个文件。"""

    source: str          # 原始绝对路径
    stored: str          # 备份目录内的相对路径
    instance: str = ""
    kind: str = "options"   # options / default / config

    @property
    def source_path(self) -> Path:
        return Path(self.source)


@dataclass
class BackupRecord:
    """一次备份。"""

    directory: Path
    label: str
    created: str
    entries: list[BackupEntry] = field(default_factory=list)
    note: str = ""

    @property
    def title(self) -> str:
        return f"{self.created}  {self.label}"

    @property
    def file_count(self) -> int:
        return len(self.entries)

    def manifest_path(self) -> Path:
        return self.directory / MANIFEST_NAME

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "created": self.created,
            "note": self.note,
            "entries": [
                {"source": e.source, "stored": e.stored,
                 "instance": e.instance, "kind": e.kind}
                for e in self.entries
            ],
        }

    @classmethod
    def from_dict(cls, directory: Path, data: dict) -> "BackupRecord":
        entries = [BackupEntry(source=e.get("source", ""),
                               stored=e.get("stored", ""),
                               instance=e.get("instance", ""),
                               kind=e.get("kind", "options"))
                   for e in data.get("entries", [])]
        return cls(directory=directory,
                   label=str(data.get("label") or directory.name),
                   created=str(data.get("created") or ""),
                   entries=entries,
                   note=str(data.get("note") or ""))


class BackupManager:
    """管理备份目录。"""

    def __init__(self, root: Path, keep: int = 40) -> None:
        self.root = Path(root)
        self.keep = keep

    # -- 创建 ------------------------------------------------------------
    def create(self, files: list[tuple[Path, str, str]],
               label: str = "同步前", note: str = "") -> BackupRecord | None:
        """备份若干文件。

        ``files`` 是 ``[(路径, 实例名, 类型)]``。不存在的文件会被跳过。
        """
        existing = [(p, inst, kind) for p, inst, kind in files if p.is_file()]
        if not existing:
            return None

        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe_label = "".join(c for c in label if c not in '\\/:*?"<>|').strip() or "backup"
        directory = self.root / f"{stamp}_{safe_label}"
        counter = 1
        while directory.exists():
            directory = self.root / f"{stamp}_{safe_label}_{counter}"
            counter += 1

        files_dir = directory / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        record = BackupRecord(directory=directory, label=label,
                              created=time.strftime("%Y-%m-%d %H:%M:%S"),
                              note=note)
        used_names: set[str] = set()
        for index, (source, instance, kind) in enumerate(existing, 1):
            name = f"{index:03d}_{source.name}"
            while name in used_names:
                name = f"{index:03d}_{len(used_names)}_{source.name}"
            used_names.add(name)
            try:
                shutil.copy2(source, files_dir / name)
            except OSError:
                continue
            record.entries.append(BackupEntry(source=str(source), stored=f"files/{name}",
                                              instance=instance, kind=kind))

        if not record.entries:
            shutil.rmtree(directory, ignore_errors=True)
            return None

        self._write_manifest(record)
        self.prune()
        return record

    def _write_manifest(self, record: BackupRecord) -> None:
        record.directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
        tmp = record.manifest_path().with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, record.manifest_path())

    # -- 列出 / 载入 ------------------------------------------------------
    def list(self) -> list[BackupRecord]:
        if not self.root.is_dir():
            return []
        out: list[BackupRecord] = []
        for directory in sorted(self.root.iterdir(), reverse=True):
            if not directory.is_dir():
                continue
            manifest = directory / MANIFEST_NAME
            if not manifest.is_file():
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append(BackupRecord.from_dict(directory, data))
        return out

    # -- 还原 ------------------------------------------------------------
    def restore(self, record: BackupRecord,
                only: list[str] | None = None) -> tuple[int, list[str]]:
        """把备份写回原路径。

        返回 ``(成功数, 错误列表)``。还原前会先把**当前**文件另存一份，
        免得「还原错了」变成不可逆操作。
        """
        errors: list[str] = []
        restored = 0
        wanted = set(only) if only else None

        pre = self.create(
            [(e.source_path, e.instance, e.kind) for e in record.entries
             if wanted is None or e.source in wanted],
            label="还原前快照",
            note=f"还原 {record.title} 之前自动保存",
        )
        if pre is None:
            # 目标文件都不存在（例如实例已删除），仍然继续还原
            pass

        for entry in record.entries:
            if wanted is not None and entry.source not in wanted:
                continue
            stored = record.directory / entry.stored
            if not stored.is_file():
                errors.append(f"备份内缺少文件：{entry.stored}")
                continue
            target = Path(entry.source)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(stored, target)
                restored += 1
            except OSError as exc:
                errors.append(f"{target}：{exc}")
        return restored, errors

    def delete(self, record: BackupRecord) -> bool:
        if record.directory.is_dir():
            shutil.rmtree(record.directory, ignore_errors=True)
            return True
        return False

    # -- 清理 ------------------------------------------------------------
    def prune(self) -> int:
        """只保留最近 ``keep`` 份备份。"""
        records = self.list()
        removed = 0
        for record in records[self.keep:]:
            if self.delete(record):
                removed += 1
        return removed

    def total_size(self) -> int:
        total = 0
        if not self.root.is_dir():
            return 0
        for path in self.root.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
        return total
