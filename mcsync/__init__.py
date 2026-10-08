# -*- coding: utf-8 -*-
"""MCKeyBinder 按键同步器 —— 核心库。

一个「不装任何 Mod」的 Minecraft 跨整合包 / 跨实例按键设置同步器。

设计要点（来自对真实 options.txt 与已有 Mod 的调研）：
  * 只在 ``options.txt`` 层面工作，因此不需要往任何整合包里装 Mod。
  * **只写目标实例已经认识的按键**：Minecraft 每次退出都会整份重写 options.txt，
    并且「只保存自己有的值」，不认识的行会被静默删除。所以不认识的按键绝不能写。
  * 绝不整文件替换，只按条目 merge，保留未知行与原始顺序。
  * 写入必须 UTF-8 无 BOM、沿用原有换行符（实测为 CRLF），否则 Minecraft 可能整份重置选项。
"""

__all__ = [
    "keycodes",
    "optionsfile",
    "instances",
    "modscan",
    "profile",
    "diff",
    "conflict",
    "sync",
    "backups",
    "configfiles",
    "semantic",
]

__version__ = "1.0.0"
APP_NAME = "MCKeyBinder 按键同步器"
