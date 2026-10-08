# -*- coding: utf-8 -*-
"""给主要流程计时 + cProfile，看看时间花在哪。

只读：不动任何 options.txt。

    python tests/perf_probe.py            # 计时 + 热点
    python tests/perf_probe.py --cold     # 顺手清掉 mod 缓存，测冷启动
"""

from __future__ import annotations

import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcsync.app import App  # noqa: E402


def timed(label: str, fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    cost = time.perf_counter() - start
    print(f"  {label:<34} {cost * 1000:8.1f} ms")
    return result


def profile(label: str, fn, *args, **kwargs):
    pr = cProfile.Profile()
    pr.enable()
    result = fn(*args, **kwargs)
    pr.disable()
    buf = io.StringIO()
    pstats.Stats(pr, stream=buf).sort_stats("tottime").print_stats(10)
    print(f"\n===== {label} 热点 =====")
    lines = buf.getvalue().splitlines()
    head = next((i for i, line in enumerate(lines) if "ncalls" in line), None)
    if head is not None:
        for line in lines[head:]:
            if line.strip():
                print("  " + line)


def main() -> int:
    if "--cold" in sys.argv:
        cache = App().cache_dir / "mods.json"
        if cache.is_file():
            cache.unlink()
            print("已清掉 mod 缓存")

    app = App()
    print("\n===== 计时 =====")
    instances = timed("发现实例（不扫盘）", app.discover_instances, False)
    if not instances:
        print("没有实例，跳过。")
        return 0
    with_options = [i for i in instances if i.exists]
    if not with_options:
        print("没有带 options.txt 的实例，跳过。")
        return 0

    timed("扫描 mod（有缓存就很快）", app.ensure_mod_index, with_options)
    profile("扫描 mod", app.ensure_mod_index, with_options)

    source = with_options[0]
    profile("抓取主配置", app.capture_profile, source, "性能探针")

    profiles = [p for p in app.load_profiles() if p.name != "性能探针"]
    profile_obj = profiles[0] if profiles else app.capture_profile(source, "性能探针2")
    profile("实例对比", app.make_diff, profile_obj, with_options)
    diff = app.make_diff(profile_obj, with_options)

    policy = app.make_policy()
    selected = {i.key: set(profile_obj.keybinds) for i in with_options}
    profile("生成同步计划", app.make_plan, profile_obj, with_options,
            selected, None, None, policy)
    plan = app.make_plan(profile_obj, with_options, selected, None, None, policy)
    print(f"\n对比行数 {len(diff.rows)}，计划涉及 {len(plan.plans)} 个文件，"
          f"按键改动 {sum(len(p.keybinds) for p in plan.plans)} 项，"
          f"设置改动 {sum(len(p.options) for p in plan.plans)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
