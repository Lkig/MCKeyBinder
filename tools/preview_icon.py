# -*- coding: utf-8 -*-
"""把 app.ico 里各尺寸渲染出来拼成一张对比图，用来肉眼检查小尺寸可读性。"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ico = ROOT / "assets" / "app.ico"

CANDIDATES = (16, 24, 32, 48, 64, 128, 256)
dims = []
for n in CANDIDATES:
    try:
        im = Image.open(ico)
        im.size = (n, n)
        im.load()
    except Exception:  # noqa: BLE001 - 这一档没存就直接跳过
        continue
    dims.append(n)
print("ICO 可读尺寸:", dims)

scale = 6
tiles = []
for n in dims:
    im = Image.open(ico)
    im.size = (n, n)
    im.load()
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    if n < 64:
        im = im.resize((n * scale, n * scale), Image.NEAREST)
    tiles.append((n, im))

pad = 10
W = sum(t.width + pad for _, t in tiles) + pad
H = max(t.height for _, t in tiles) + 2 * pad
board = Image.new("RGBA", (W, H), (245, 245, 245, 255))
x = pad
for w, t in tiles:
    board.paste(t, (x, pad + (H - 2 * pad - t.height) // 2), t)
    x += t.width + pad
out = ROOT / "assets" / "_preview.png"
board.save(out)
print("对比图:", out, board.size, "（左起：", ", ".join(str(w) for w, _ in tiles), "）")
