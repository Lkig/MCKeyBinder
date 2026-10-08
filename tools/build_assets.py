# -*- coding: utf-8 -*-
"""生成图标与 Windows 快捷方式。

跑一次就够了（改图标设计时才需要重跑）::

    python tools/build_assets.py

产出：
* ``assets/app.ico``            —— 一颗印着草方块的键帽（多尺寸）
* ``assets/app_256.png``        —— 预览用大图
* ``启动按键同步器.lnk``        —— 双击即启动，无控制台窗口、无安全警告

快捷方式之所以没有安全警告：Windows 的「打开文件 - 安全警告」只对
.bat/.cmd/.vbs/.exe 这类会在脚本宿主里执行、且带有「来自 Internet」标记
（Zone.Identifier）的文件弹出；.lnk 直接指向 pythonw.exe，两者都不沾。
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# MC 原版 GUI 的经典配色
FACE = (198, 198, 198)      # 按钮/面板正面 #C6C6C6
LIGHT = (255, 255, 255)     # 高光 #FFFFFF
DARK = (85, 85, 85)         # 阴影 #555555
BLACK = (0, 0, 0)
SLOT = (139, 139, 139)      # 物品槽凹陷 #8B8B8B
STONE = (125, 125, 125)     # 石头底
GREEN = (90, 197, 79)       # 经验条绿

# 草方块配色（MC 原版贴图取样）
GRASS = (106, 170, 64)      # 顶面绿
GRASS_LIGHT = (130, 190, 84)
GRASS_DARK = (80, 133, 48)
DIRT = (134, 96, 67)        # 泥土 #866043
DIRT_LIGHT = (151, 112, 79)
DIRT_DARK = (104, 73, 50)

S = 256


def _box(d: ImageDraw.ImageDraw, box, face, b=6) -> None:
    """一格 MC 风格的立体方块。

    和 MC 的按钮贴图一样是「三明治」结构：最外圈黑边，紧挨着左上白高光、
    右下灰阴影，中间才是正面颜色。用同心矩形画，比 ``line(width=)`` 可控
    ——PIL 的 line 是以坐标为中心向两边扩的，会糊掉 1 像素的边。
    """
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=BLACK)
    d.rectangle((x0 + b, y0 + b, x1 - b, y1 - b), fill=face)
    d.rectangle((x0 + b, y0 + b, x1 - b, y0 + 2 * b - 1), fill=LIGHT)
    d.rectangle((x0 + b, y0 + b, x0 + 2 * b - 1, y1 - b), fill=LIGHT)
    d.rectangle((x0 + b, y1 - 2 * b + 1, x1 - b, y1 - b), fill=DARK)
    d.rectangle((x1 - 2 * b + 1, y0 + b, x1 - b, y1 - b), fill=DARK)


def build_grass(size: int, b: int | None = None, seed: int = 20261008) -> Image.Image:
    """一颗印着草方块的键帽。

    结构还是 MC 键帽的那套「三明治」：最外圈黑边 + 左上白高光 + 右下灰阴影，
    中间那块正面画成草方块——上面一层绿草皮、下沿是锯齿状，下面是带斑点的泥土。
    贴图按单元格铺，格子数随尺寸变（16px 下还用 16×16 格就糊成一团了）。
    """
    rng = random.Random(seed)
    if b is None:
        b = max(1, round(size * 0.031))

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 键帽本体（正面先铺泥土色，后面整块都会被草皮/泥土格子覆盖）
    _box(d, (0, 0, size - 1, size - 1), DIRT, b=b)

    # 真正干净的正面区域：黑边和高光/阴影各占 b，所以要缩进 2b
    fx0 = fy0 = 2 * b
    fx1 = fy1 = size - 1 - 2 * b
    fw = fx1 - fx0 + 1
    fh = fy1 - fy0 + 1
    if fw < 3 or fh < 3:
        return img

    cells = max(3, min(16, fw // 7))
    greens = (GRASS, GRASS, GRASS, GRASS_LIGHT, GRASS_DARK)
    dirts = (DIRT, DIRT, DIRT, DIRT_LIGHT, DIRT_DARK)

    # 草皮下沿的锯齿：每列深浅不一样，才不会像一条直线
    base = max(1, round(cells * 0.3))
    depth = [max(1, min(cells - 1, base + rng.choice((-1, 0, 0, 1))))
             for _ in range(cells)]

    for gy in range(cells):
        y0 = fy0 + round(gy * fh / cells)
        y1 = fy0 + round((gy + 1) * fh / cells) - 1
        if y1 < y0:
            continue
        for gx in range(cells):
            x0 = fx0 + round(gx * fw / cells)
            x1 = fx0 + round((gx + 1) * fw / cells) - 1
            if x1 < x0:
                continue
            fill = rng.choice(greens if gy < depth[gx] else dirts)
            d.rectangle((x0, y0, x1, y1), fill=fill)

    return img


#: 每个尺寸单独渲染，避免小图标糊成一团
ICON_TIERS: list[int] = [256, 128, 64, 48, 32, 24, 16]


def make_icon() -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    tiers = [build_grass(n) for n in ICON_TIERS]
    png = ASSETS / "app_256.png"
    tiers[0].save(png)
    ico = ASSETS / "app.ico"
    tiers[0].save(ico, format="ICO", append_images=tiers[1:],
                  sizes=[(t.width, t.height) for t in tiers])
    return ico


def find_pythonw() -> Path | None:
    """找一个「用户自己的」pythonw.exe。

    不要直接信 ``sys.executable``——如果这个脚本是被某个自带的运行时
    （比如 IDE、工具链里那个 python）跑起来的，快捷方式就会指向那个临时解释器，
    换个环境就打不开了。所以先看环境变量，再看 py launcher 报的路径，
    最后才退回 ``sys.executable``。
    """
    candidates: list[Path] = []
    env = os.environ.get("MCKEYBINDER_PYTHONW")
    if env:
        candidates.append(Path(env))
    # py launcher 报出来的才是「默认安装」的那个 Python
    try:
        out = subprocess.run(["py", "-3", "-c", "import sys; print(sys.executable)"],
                             capture_output=True, text=True, timeout=20)
        if out.returncode == 0 and out.stdout.strip():
            candidates.append(Path(out.stdout.strip()).with_name("pythonw.exe"))
    except (OSError, subprocess.SubprocessError):
        pass
    candidates.append(Path(sys.executable).with_name("pythonw.exe"))
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def make_shortcut(ico: Path) -> Path | None:
    """用 WScript.Shell 建一个 .lnk，指向 pythonw.exe，完全无控制台。"""
    pyw = find_pythonw()
    if pyw is None:
        print("! 找不到 pythonw.exe，跳过快捷方式")
        return None
    print(f"  pythonw: {pyw}")

    lnk = ROOT / "启动按键同步器.lnk"
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{lnk}')
$sc.TargetPath       = '{pyw}'
$sc.Arguments        = '"' + '{ROOT / "main.py"}' + '"'
$sc.WorkingDirectory = '{ROOT}'
$sc.IconLocation     = '{ico},0'
$sc.Description      = 'MCKeyBinder 按键同步器 - 一键同步整合包按键设置'
$sc.Save()
Write-Output 'OK'
"""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"! 建快捷方式失败：{exc}")
        return None
    if lnk.exists():
        return lnk
    print(f"! 建快捷方式失败：{out.stderr.strip() or out.stdout.strip()}")
    return None


def main() -> int:
    ico = make_icon()
    print(f"图标：{ico}")
    lnk = make_shortcut(ico)
    if lnk:
        print(f"快捷方式：{lnk}")
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    raise SystemExit(main())
