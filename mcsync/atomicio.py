"""原子写文本文件。

Windows 上有个很坑的失败模式：两个线程 / 两个进程同时往同一个目标保存时，
如果临时文件名固定（`mods.tmp`、`settings.tmp`），后一个写文件的人会撞上
`[WinError 32] 另一个程序正在使用此文件`，而且 `os.replace` 也会随机失败。

这里的做法是：
1. 临时文件名带上 pid 和自增序号，谁都不会踩到谁；
2. 换名失败时短暂退避重试几次（杀毒软件、索引服务会短时间占住文件）；
3. `strict=False` 时任何失败都只是返回 False —— 缓存、设置这类数据丢了
   顶多下次重算，不该把异常抛到界面上。
"""

from __future__ import annotations

import itertools
import os
import time
from pathlib import Path

_TMP_COUNTER = itertools.count(1)
_RETRIES = 6


def _cleanup(tmp: Path) -> None:
    try:
        tmp.unlink()
    except OSError:
        pass


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8",
                      strict: bool = True, retries: int = _RETRIES) -> bool:
    """把 text 原子地写到 path。

    返回 True 表示写成功；`strict=False` 时失败返回 False 而不是抛异常。
    """
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{next(_TMP_COUNTER)}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding=encoding)
    except OSError:
        _cleanup(tmp)
        if strict:
            raise
        return False

    last: OSError | None = None
    for attempt in range(retries):
        try:
            os.replace(tmp, path)
            return True
        except OSError as exc:  # 被占用 / 杀毒软件短暂锁定
            last = exc
            time.sleep(0.03 * (attempt + 1))
    _cleanup(tmp)
    if strict and last is not None:
        raise last
    return False
