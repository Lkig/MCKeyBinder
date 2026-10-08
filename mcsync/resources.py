# -*- coding: utf-8 -*-
"""程序「在哪儿」——源码运行和打包成 exe 运行的路径差异都收在这里。

两种跑法要分开看：

============  ==========================  ==========================
             **只读资源**（assets/ 图标）   **可写数据**（data/ 目录）
源码运行     项目根                     项目根
PyInstaller  解包临时目录（``_MEIPASS``）  **exe 所在目录**
============  ==========================  ==========================

只读资源非分开不可：onefile 打包时 python 代码和 ``assets/`` 一起被解到
``%TEMP%\\_MEIxxxx``，下次运行又换一个目录，所以写在那儿的 data/ 会被丢掉。
反过来 ``data/`` 必须固定在 exe 旁边，用户才能把主配置和备份带着走。
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["is_frozen", "resource_dir", "app_dir"]


def is_frozen() -> bool:
    """是不是被 PyInstaller 之类的打包器塞进 exe 里在跑。"""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """只读资源（``assets/app.ico`` 等）所在的目录。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """可写数据（``data/``）应该放在哪儿：exe 版就是 exe 旁边，绿色版行为。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
