# -*- coding: utf-8 -*-
"""把 MCKeyBinder 打包成单文件 exe（PyInstaller）。

先准备一个带 PyInstaller 的环境，再用它跑本脚本::

    python -m venv .venv
    .venv\\Scripts\\python -m pip install -r requirements-build.txt
    .venv\\Scripts\\python tools\\build_exe.py

产物在 ``dist/MCKeyBinder.exe``：单文件、双击即用、自带图标、不弹控制台。
它是**绿色版**——首次运行会在 exe 旁边建一个 ``data/`` 放主配置和备份，
想搬走就把 exe 和 data/ 一起拷走。

几点容易踩的坑，都在这儿处理掉了：

* ``gui/`` 和 ``mcsync/`` 是包内相对导入 + ``main()`` 里的函数级导入，
  静态分析偶尔跟丢，所以显式把两个包的模块全列进 ``--hidden-import``。
* ``assets/`` 得一起打进去（``--add-data``），否则窗口图标和托盘图标是空的。
  运行时它落在 ``sys._MEIPASS``，由 ``mcsync/resources.py`` 找出来。
* tkinter 的 Tcl/Tk 数据是 PyInstaller 自动收的，不用管。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "_build" / "pyi"
SPEC = ROOT / "_build"

APP_NAME = "MCKeyBinder"
ICON = ROOT / "assets" / "app.ico"


def hidden_imports() -> list[str]:
    """gui/ 与 mcsync/ 下的模块全部显式声明，别指望静态分析。"""
    names = []
    for package in ("gui", "mcsync"):
        for path in sorted((ROOT / package).glob("*.py")):
            if path.stem == "__init__":
                continue
            names += ["--hidden-import", f"{package}.{path.stem}"]
    return names


def version_file() -> Path | None:
    """给 exe 属性页填上产品名/版本号——没它的话右键属性一片空白。"""
    try:
        sys.path.insert(0, str(ROOT))
        from mcsync import APP_NAME, __version__  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    ver = tuple(int(x) for x in __version__.split(".")) + (0,)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver[:4]!r}, prodvers={ver[:4]!r},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404b0', [
        StringStruct('CompanyName', 'Lkig'),
        StringStruct('FileDescription', 'MCKeyBinder 按键同步器'),
        StringStruct('FileVersion', '{__version__}'),
        StringStruct('InternalName', '{APP_NAME}'),
        StringStruct('OriginalFilename', '{APP_NAME}.exe'),
        StringStruct('ProductName', 'MCKeyBinder 按键同步器'),
        StringStruct('ProductVersion', '{__version__}'),
        StringStruct('LegalCopyright', 'MIT License')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    path = WORK / "version_info.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    console = "--console" in argv  # 排错用：留一个黑框好看见 traceback
    onedir = "--onedir" in argv    # 目录版：不往 %TEMP% 自解压，启动更快
    try:
        import PyInstaller.__main__ as pyi  # noqa: PLC0415
    except ImportError:
        print("没装 PyInstaller。先跑：\n"
              "  python -m venv .venv\n"
              "  .venv\\Scripts\\python -m pip install -r requirements-build.txt",
              file=sys.stderr)
        return 2

    if not ICON.exists():
        print(f"图标不存在：{ICON}\n先跑 tools/build_assets.py", file=sys.stderr)
        return 2

    # assets/_* 是截图、预览之类的临时产物，会被 --add-data 一起塞进 exe。
    # （.gitignore 里已经排除了它们，所以仓库干净，但本地打包前得自己看一眼。）
    stray = sorted(p for p in ICON.parent.iterdir() if p.name.startswith("_"))
    if stray:
        print("assets/ 里有临时产物，会被打进 exe：", file=sys.stderr)
        for path in stray:
            print(f"  {path}", file=sys.stderr)
        print("先删掉它们再打包（或确认无所谓）。", file=sys.stderr)

    shutil.rmtree(WORK, ignore_errors=True)

    name = f"{APP_NAME}-debug" if console else APP_NAME
    # 三种产物各放各的目录，互不覆盖（onefile 是 dist/onefile/MCKeyBinder.exe，
    # onedir 是 dist/onedir/MCKeyBinder/MCKeyBinder.exe，同名也不打架）
    dist = DIST / ("onedir" if onedir else "console" if console else "onefile")
    shutil.rmtree(dist, ignore_errors=True)
    args = [
        str(ROOT / "main.py"),
        "--name", name,
        "--onedir" if onedir else "--onefile",
        "--console" if console else "--windowed",   # 双击不弹黑框
        "--noconfirm",
        "--clean",
        "--icon", str(ICON),
        "--add-data", f"{ICON.parent}{os.pathsep}assets",
        "--distpath", str(dist),
        "--workpath", str(WORK),
        "--specpath", str(SPEC),
        "--log-level", "WARN",
    ]
    args += hidden_imports()
    vf = version_file()
    if vf:
        args += ["--version-file", str(vf)]

    print(f"打包 {name}（{len(args)} 个参数）……")
    pyi.run(args)

    exe = (dist / name / f"{name}.exe") if onedir else (dist / f"{name}.exe")
    if not exe.exists():
        print("打包失败：没看到 exe", file=sys.stderr)
        return 1
    total = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file())
    print(f"\n完成：{exe}  ({total / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
