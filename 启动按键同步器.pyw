# -*- coding: utf-8 -*-
"""双击这个文件即可启动图形界面。

用 ``.pyw`` 扩展名的好处：Windows 会用 ``pythonw.exe`` 打开它，
**完全不出现控制台黑窗口**，也就不会「闪一下」。出错时会弹出对话框而不是静默退出。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
