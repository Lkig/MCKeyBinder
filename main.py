# -*- coding: utf-8 -*-
"""MCKeyBinder 按键同步器 —— 统一启动入口。

不管是双击 ``启动按键同步器.pyw``、跑 ``命令行.bat`` 还是直接
``python main.py``，都从这里进。

这里是**唯一**负责「把出错信息显示给人看」的地方：图形界面模式下用弹窗，
控制台模式下打印堆栈。这样不会出现「窗口闪一下就没了、什么都不知道」的情况。
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 打包成 exe 后 __file__ 指的是临时解包目录；data/ 要落在 exe 旁边，
# 所以相对路径的工作目录得跟着 mcsync.resources 的说法走。
try:
    from mcsync.resources import app_dir as _app_dir

    WORKDIR = _app_dir()
except Exception:  # noqa: BLE001 - 模块还没就绪时退回源码布局
    WORKDIR = ROOT


def show_error(title: str, text: str) -> None:
    """尽力把错误显示出来：优先图形弹窗，退回到控制台。"""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, text)
        root.destroy()
        return
    except Exception:  # noqa: BLE001 - 弹窗失败就退回控制台
        pass

    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}", file=sys.stderr)
    print(text, file=sys.stderr)
    try:
        input("\n按回车键关闭……")
    except (EOFError, KeyboardInterrupt):
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # 让相对路径（gui/、mcsync/）在任何工作目录下都能用
    try:
        os.chdir(WORKDIR)
    except OSError:
        pass

    try:
        from gui.app import main as gui_main
    except Exception:  # noqa: BLE001
        show_error("启动失败：无法载入程序模块",
                   traceback.format_exc() +
                   "\n\n请确认整个 MCKeyBinder 文件夹是完整的，没有被移动或删掉文件。")
        return 1

    try:
        return gui_main(argv)
    except Exception:  # noqa: BLE001
        show_error("运行出错", traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
