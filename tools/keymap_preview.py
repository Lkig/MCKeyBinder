# -*- coding: utf-8 -*-
"""键位图控件的离线预览 + 截图。

给键位图灌一批假状态，把窗口截下来存成 PNG，用来肉眼检查布局和配色。
不需要真实整合包，也不碰任何 options.txt::

    python tests/keymap_preview.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

from gui import mcstyle as mc  # noqa: E402
from gui.keymap import KeyState, KeymapCanvas, LAYOUTS  # noqa: E402

_K = "key.keyboard."


def fake_states() -> dict[str, KeyState]:
    s: dict[str, KeyState] = {}

    def put(code, state, details):
        s[code] = KeyState(state=state, count=len(details), details=details)

    put(_K + "w", "used", ["向前  [移动]"])
    put(_K + "s", "used", ["向后  [移动]"])
    put(_K + "a", "used", ["向左  [移动]"])
    put(_K + "d", "used", ["向右  [移动]"])
    put(_K + "space", "used", ["跳跃  [移动]"])
    put(_K + "left.shift", "used", ["潜行  [移动]"])
    put(_K + "left.control", "diff", ["疾跑：主配置=左Ctrl / Alpha=左Alt  [移动]"])
    put(_K + "e", "used", ["打开背包  [物品栏]"])
    put(_K + "m", "conflict", ["打开大地图  [Xaero 地图]", "打开小地图设置  [旅行地图]"])
    put(_K + "j", "conflict", ["查看配方  [JEI]", "切换任务书  [FTB 任务]",
                               "打开日志  [Jade]"])
    put(_K + "f", "used", ["交换副手  [移动]"])
    put(_K + "q", "used", ["丢弃物品  [物品栏]"])
    put(_K + "escape", "used", ["游戏菜单  [界面]"])
    put(_K + "grave.accent", "diff", ["切换视角/快捷栏：不一致"])
    put(_K + "backspace", "used", ["切换 HUD  [Jade]"])
    put("key.mouse.middle", "used", ["选取方块  [创造模式]"])
    put("key.mouse.left", "used", ["攻击/破坏  [游戏]", "确认  [界面]"])
    put(_K + "keypad.0", "used", ["测试用键"])
    return s


def main() -> int:
    root = tk.Tk()
    root.title("键位图预览")
    root.geometry("1180x760")
    fonts = mc.apply_theme(root)

    frame = ttk.Frame(root, padding=8)
    frame.pack(fill="both", expand=True)

    top = ttk.Frame(frame)
    top.pack(fill="x", pady=(0, 6))
    ttk.Label(top, text="键盘布局：").pack(side="left")
    layout_var = tk.StringVar(value=next(iter(LAYOUTS)))
    combo = ttk.Combobox(top, textvariable=layout_var, state="readonly", width=26,
                         values=list(LAYOUTS))
    combo.pack(side="left")
    ttk.Label(top, text="   （悬停看提示，点击选中）", style="Hint.TLabel").pack(side="left")

    km = KeymapCanvas(frame, fonts=fonts)
    km.pack(fill="both", expand=True)
    km.set_states(fake_states())
    combo.bind("<<ComboboxSelected>>", lambda _e: km.set_layout(layout_var.get()))

    # 详情面板占位，验证上下布局比例
    detail = ttk.Labelframe(frame, text="详情", padding=6)
    detail.pack(fill="x", pady=(6, 0))
    ttk.Label(detail, text="（点键盘上的键，这里会显示绑定了什么）").pack(anchor="w")

    root.update_idletasks()
    root.update()
    time.sleep(0.6)
    root.update()

    try:
        from PIL import ImageGrab

        root.lift()
        root.attributes("-topmost", True)
        root.update()
        time.sleep(0.4)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        out = ROOT / "assets" / "_keymap_preview.png"
        img.save(out)
        print(f"截图：{out}  {img.size}")
    except Exception as exc:  # noqa: BLE001
        print(f"截图失败（不影响控件本身）：{exc!r}")

    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
