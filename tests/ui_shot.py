# -*- coding: utf-8 -*-
"""把真实的界面截图下来，用来肉眼验收 + 放进文档。

只读：不写任何 options.txt，也不改主配置。

    python tests/ui_shot.py                 # 每个标签页各截一张
    python tests/ui_shot.py 键位图          # 只截一个标签页
    python tests/ui_shot.py --list          # 列出标签页名字
    python tests/ui_shot.py --out-dir assets --prefix _tab_

输出文件名形如 ``docs/images/ui-键位图.png``。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcsync.app import App  # noqa: E402
from gui.app import SyncApp  # noqa: E402


def pump(window, seconds: float, until=None) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        window.update()
        if until is not None and until():
            return
        time.sleep(0.02)


def tab_names(window) -> list[str]:
    return [window.notebook.tab(i, "text") for i in range(window.notebook.index("end"))]


def grab(window, out: Path) -> None:
    from PIL import ImageGrab

    window.lift()
    window.attributes("-topmost", True)
    window.update()
    time.sleep(0.7)
    window.update()
    x, y = window.winfo_rootx(), window.winfo_rooty()
    w, h = window.winfo_width(), window.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"截图：{out}  {img.size}")


def main() -> int:
    args = sys.argv[1:]
    out_dir = ROOT / "docs" / "images"
    prefix = "ui-"
    if "--out-dir" in args:
        i = args.index("--out-dir")
        out_dir = Path(args[i + 1])
        del args[i:i + 2]
    if "--prefix" in args:
        i = args.index("--prefix")
        prefix = args[i + 1]
        del args[i:i + 2]
    geometry = "1380x880"
    if "--geometry" in args:
        i = args.index("--geometry")
        geometry = args[i + 1]
        del args[i:i + 2]
    wanted = [a for a in args if not a.startswith("--")]

    app = App()
    app.discover_instances(do_drive_scan=False)
    if not app.instances or not app.load_profiles():
        print("没有真实实例或主配置可截，跳过。")
        return 0

    window = SyncApp(app, autostart=False)
    window.geometry(geometry)
    window.update()

    names = [p.name for p in app.load_profiles()]
    window.profile_var.set(names[0])
    window.on_profile_selected()
    window._after_scan(app.instances)
    # 只勾已经启动过（有 options.txt）的实例：没启动过的实例整个置为「未绑定」，
    # 会把键位图刷成一片橙色，截图没信息量。
    for inst in app.instances:
        window.instance_tree.set_checked(inst.key, bool(inst.exists))
    window.on_instance_toggle()
    # 主配置就是从这台机器上抓的，「只看有差异的」会让对比表空着，截图没信息量
    window.only_diff_var.set(False)

    window.refresh_diff()
    pump(window, 180.0, until=lambda: window.diff_table is not None)
    if window.diff_table is None:
        print("对比表没生成出来，跳过截图。")
        window.destroy()
        return 1

    tabs = tab_names(window)
    if "--list" in sys.argv:
        print("标签页：", "、".join(tabs))
        window.destroy()
        return 0
    todo = [t for t in tabs if not wanted or t in wanted]
    if not todo:
        print(f"没有匹配的标签页：{wanted}；可选 {tabs}")
        window.destroy()
        return 1

    # 键位图页先选一个冲突键，截图才有信息量
    from mcsync.keymap_model import conflict_usages

    km = window.keymap_tab
    conflicts = conflict_usages(km.usages)
    if conflicts:
        km._on_select(conflicts[0].code)

    for name in todo:
        index = tabs.index(name)
        window.notebook.select(index)
        window.update()
        pump(window, 1.2)
        try:
            grab(window, out_dir / f"{prefix}{name}.png")
        except Exception as exc:  # noqa: BLE001
            print(f"截图 {name} 失败：{exc!r}")

    if km.usages:
        print(f"键位图占用 {len(km.usages)} 个键，其中冲突 {len(conflicts)} 个")
    window.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
