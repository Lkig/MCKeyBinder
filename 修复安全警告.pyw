"""一键修掉「打开文件 - 安全警告：无法验证发布者」。

这个黄色弹框不是杀毒软件弹的，也不是「没签名」弹的 —— 它是 Windows 的
**附件管理器（Attachment Manager）** 看到文件上带着 **MOTW**（Mark of the Web，
就是 NTFS 的 `文件名:Zone.Identifier` 备用数据流）才弹的。凡是「从网上下载 /
从压缩包解开 / 从网盘同步过来」的文件都会带这个标记。

所以结论很直接：

* **给程序签名没用**（微软文档明确：自签名和未签名对 SmartScreen 是同等待遇）；
* **把 .bat 打包成 .exe 也没用**，只是把黄色框换成蓝色的 SmartScreen 框；
* **唯一的正解是去掉 MOTW，或者换一个不带 MOTW 的启动入口。**

`.bat` / `.cmd` / `.exe` / `.lnk` 属于 Windows 硬编码的「一律危险」扩展名，
注册表白名单也压不住；而 `.pyw` 不在这个表里，所以双击 `.pyw` 或指向
`pythonw.exe` 的快捷方式是最稳的入口（顺带还没有黑窗口闪一下）。

双击这个文件就行（用 pythonw 跑，没有控制台窗口）。它会：
1. 扫一遍项目目录，把所有带 MOTW 的文件列出来并去掉标记；
2. 重建桌面 / 开始菜单的快捷方式（指向 `pythonw.exe`，无 MOTW）；
3. 弹窗汇报结果。

只想看不想改的话，用命令行跑：`python 修复安全警告.pyw --check`
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHORTCUT_NAME = "MCKeyBinder 按键同步器.lnk"
PROJECT_SHORTCUT_NAME = "启动按键同步器.lnk"
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", "dist", "build"}


# --------------------------------------------------------------------------
# MOTW
# --------------------------------------------------------------------------

def find_motw(root: Path) -> list[Path]:
    """列出 root 下面所有带 Zone.Identifier 的文件。"""
    hits: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if has_motw(path):
                hits.append(path)
    return hits


def has_motw(path: Path) -> bool:
    try:
        with open(f"{path}:Zone.Identifier", "rb"):
            return True
    except OSError:
        return False


def clear_motw(path: Path) -> bool:
    """删掉 Zone.Identifier 流；成功或本来就没有都算成功。"""
    try:
        os.remove(f"{path}:Zone.Identifier")
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# 快捷方式
# --------------------------------------------------------------------------

def pythonw() -> str:
    """找一个 pythonw.exe —— 没有控制台窗口的那个。"""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    if candidate.is_file():
        return str(candidate)
    return str(exe)


def shortcut_targets() -> list[Path]:
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    out = [home / "Desktop" / SHORTCUT_NAME,
           appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / SHORTCUT_NAME]
    # 项目里本来就带了「启动按键同步器.lnk」，不要再另起一个名字
    out.append(ROOT / PROJECT_SHORTCUT_NAME)
    return out


def shortcut_ok(path: Path) -> bool:
    """已经指向同一个 pythonw + main.py 就不用重建。"""
    if not path.is_file():
        return False
    try:
        import subprocess
        script = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{path}'); "
            "$s.TargetPath + '|' + $s.Arguments + '|' + $s.WorkingDirectory"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return False
        parts = (proc.stdout or "").strip().split("|")
        if len(parts) != 3:
            return False
        return (parts[0].lower() == pythonw().lower()
                and parts[1].strip('"').lower() == str(ROOT / "main.py").lower()
                and parts[2].lower() == str(ROOT).lower())
    except Exception:  # pragma: no cover - 环境相关
        return False


def make_shortcut(path: Path) -> tuple[bool, str]:
    """用 WScript.Shell 建快捷方式（必须指向 pythonw.exe，才没有黑窗口）。"""
    if shortcut_ok(path):
        return True, "已存在"
    try:
        import subprocess
        script = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{path}'); "
            f"$s.TargetPath = '{pythonw()}'; "
            f"$s.Arguments = '\"{ROOT / 'main.py'}\"'; "
            f"$s.WorkingDirectory = '{ROOT}'; "
            f"$s.IconLocation = '{ROOT / 'assets' / 'app.ico'},0'; "
            f"$s.Description = 'MCKeyBinder 按键同步器 - 一键同步整合包按键设置'; "
            "$s.Save()"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "powershell 失败").strip()
        return path.is_file(), "ok"
    except Exception as exc:  # pragma: no cover - 环境相关
        return False, str(exc)


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def run(check_only: bool = False) -> dict:
    hits = find_motw(ROOT)
    cleared: list[Path] = []
    failed: list[Path] = []
    if not check_only:
        for path in hits:
            (cleared if clear_motw(path) else failed).append(path)

    links: list[tuple[Path, bool, str]] = []
    if not check_only:
        for target in shortcut_targets():
            ok, msg = make_shortcut(target)
            links.append((target, ok, msg))
    return {"found": hits, "cleared": cleared, "failed": failed, "links": links}


def report(result: dict, check_only: bool) -> str:
    found = result["found"]
    lines: list[str] = []
    if not found:
        lines.append("✓ 项目目录里没有任何带「安全警告」标记（MOTW）的文件。")
        lines.append("")
        lines.append("也就是说：直接双击「" + SHORTCUT_NAME + "」或")
        lines.append("「启动按键同步器.pyw」不应该再弹黄色警告框。")
        lines.append("如果还在弹，请把弹框的**标题和正文原文**发我 ——")
        lines.append("黄色框（附件管理器）和蓝色框（SmartScreen）是两回事。")
    else:
        if check_only:
            lines.append(f"发现 {len(found)} 个带 MOTW 的文件（未修改）：")
        else:
            lines.append(f"发现 {len(found)} 个带 MOTW 的文件，"
                         f"已去掉 {len(result['cleared'])} 个：")
        for path in found[:40]:
            try:
                shown = path.relative_to(ROOT)
            except ValueError:
                shown = path
            lines.append(f"    {shown}")
        if len(found) > 40:
            lines.append(f"    …还有 {len(found) - 40} 个")
        if result["failed"]:
            lines.append("")
            lines.append("以下文件去标记失败（多半是被占用），关闭相关程序后重跑：")
            for path in result["failed"]:
                lines.append(f"    {path}")

    if not check_only and result["links"]:
        lines.append("")
        lines.append("快捷方式：")
        for path, ok, msg in result["links"]:
            mark = "✓" if ok else "✗"
            lines.append(f"    {mark} {path}")
            if not ok:
                lines.append(f"        {msg}")

    lines.append("")
    lines.append("最稳的启动顺序：桌面快捷方式 → 启动按键同步器.pyw → （排错时才用）.bat")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    result = run(check_only=check_only)
    text = report(result, check_only)
    print(text)
    if "--no-gui" in argv:
        return 0
    try:
        import tkinter as tk
        from tkinter import scrolledtext

        win = tk.Tk()
        win.title("MCKeyBinder 启动警告检查")
        win.geometry("720x460")
        win.minsize(560, 320)
        box = scrolledtext.ScrolledText(win, wrap="word", font=("Microsoft YaHei UI", 10))
        box.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        box.insert("1.0", text)
        box.configure(state="disabled")
        tk.Button(win, text="知道了", width=12,
                  command=win.destroy).pack(pady=(0, 10))
        win.mainloop()
    except Exception as exc:  # pragma: no cover
        print("（没法弹窗，内容见上面）", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
