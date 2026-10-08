# -*- coding: utf-8 -*-
"""合成数据自测：不碰任何真实整合包，端到端验证同步链路。

构造三个假实例：

* **A** —— 1.21.1 / NeoForge，现代命名键码，装了「小地图」和「配方查看」两个假 mod
* **B** —— 1.21.1 / NeoForge，同 mod 但按键不同，用来验证同步
* **C** —— 1.12.2 / Forge，数字键码，用来验证跨版本转换
* **D** —— 少装一个 mod，用来验证「只写目标认识的按键」

运行：``python cli.py selftest -v``
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcsync.app import App
from mcsync.backups import BackupManager
from mcsync.diff import ChangeKind, find_conflicts
from mcsync.instances import scan_game_dir
from mcsync.keycodes import KeyCombo
from mcsync.legacy_codes import convert_value, legacy_to_named, named_to_legacy
from mcsync.modscan import ModIndex, scan_mods_dir
from mcsync.naming import NamingResolver
from mcsync.optionsfile import OptionsFile
from mcsync.profile import Profile
from mcsync.sync import SyncPolicy, build_plan

# --------------------------------------------------------------------------
# 断言框架
# --------------------------------------------------------------------------

_PASS = 0
_FAIL: list[str] = []
_VERBOSE = False


def check(condition: bool, label: str, detail: str = "") -> bool:
    global _PASS
    if condition:
        _PASS += 1
        if _VERBOSE:
            print(f"  ✓ {label}")
    else:
        _FAIL.append(label + (f"  —— {detail}" if detail else ""))
        print(f"  ✗ {label}" + (f"  —— {detail}" if detail else ""))
    return bool(condition)


def eq(actual, expected, label: str) -> bool:
    return check(actual == expected, label, f"期望 {expected!r}，实际 {actual!r}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# --------------------------------------------------------------------------
# 造数据
# --------------------------------------------------------------------------

MODERN_OPTIONS = """\
lang:zh_cn
fov:0.0
guiScale:3
gamma:0.5
renderDistance:12
soundCategory_master:1.0
tutorialStep:none
resourcePacks:["vanilla"]
{keys}"""

VANILLA_KEYS_MODERN = [
    ("key_key.attack", "key.mouse.left"),
    ("key_key.use", "key.mouse.right"),
    ("key_key.forward", "key.keyboard.w"),
    ("key_key.left", "key.keyboard.a"),
    ("key_key.back", "key.keyboard.s"),
    ("key_key.right", "key.keyboard.d"),
    ("key_key.jump", "key.keyboard.space"),
    ("key_key.sneak", "key.keyboard.left.shift"),
    ("key_key.sprint", "key.keyboard.left.control"),
    ("key_key.drop", "key.keyboard.q"),
    ("key_key.inventory", "key.keyboard.e"),
    ("key_key.chat", "key.keyboard.t"),
    ("key_key.playerlist", "key.keyboard.tab"),
    ("key_key.pickItem", "key.mouse.middle"),
    ("key_key.togglePerspective", "key.keyboard.f5"),
    ("key_key.screenshot", "key.keyboard.f2"),
]

MINIMAP_KEYS = [
    ("key_gui.xaero_open_map", "key.keyboard.m"),
    ("key_gui.xaero_toggle_map", "key.keyboard.unknown"),
    ("key_gui.xaero_waypoints_key", "key.keyboard.u"),
    ("key_gui.xaero_new_waypoint", "key.keyboard.b"),
]

RECIPE_KEYS = [
    ("key_key.jei.showRecipe", "key.keyboard.r"),
    ("key_key.jei.showUses", "key.keyboard.u"),
    ("key_key.jei.toggleOverlay", "key.keyboard.o:CONTROL"),
]


def write_options(path: Path, keys: list[tuple[str, str]],
                  newline: str = "\r\n", bom: bool = False,
                  extra: dict[str, str] | None = None) -> None:
    body = MODERN_OPTIONS.format(
        keys="".join(f"{n}:{v}{newline}" for n, v in keys))
    if extra:
        lines = body.rstrip("\r\n").split(newline)
        for name, value in extra.items():
            lines.insert(0, f"{name}:{value}")
        body = newline.join(lines) + newline
    data = body.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def make_mod_jar(path: Path, mod_id: str, name: str,
                 lang: dict[str, str], nested: list[tuple[str, str, dict]] | None = None,
                 loader: str = "neoforge") -> None:
    """造一个假 mod jar（可带 jar-in-jar）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        if loader == "neoforge":
            zf.writestr("META-INF/neoforge.mods.toml",
                        f'[[mods]]\nmodId="{mod_id}"\ndisplayName="{name}"\nversion="1.0"\n')
        else:
            zf.writestr("fabric.mod.json",
                        json.dumps({"id": mod_id, "name": name, "version": "1.0"}))
        zf.writestr(f"assets/{mod_id}/lang/en_us.json",
                    json.dumps(lang, ensure_ascii=False))
        for nested_id, nested_name, nested_lang in (nested or []):
            nested_buf = io.BytesIO()
            with zipfile.ZipFile(nested_buf, "w") as nz:
                nz.writestr("META-INF/neoforge.mods.toml",
                            f'[[mods]]\nmodId="{nested_id}"\ndisplayName="{nested_name}"\n')
                nz.writestr(f"assets/{nested_id}/lang/en_us.json",
                            json.dumps(nested_lang, ensure_ascii=False))
            zf.writestr(f"META-INF/jarjar/{nested_id}-1.0.jar", nested_buf.getvalue())
    path.write_bytes(buffer.getvalue())


def build_fixture(root: Path) -> dict:
    """搭出 A/B/C/D 四个假实例，返回路径表。"""
    mc = root / ".minecraft"
    paths: dict = {"root": root, "mc": mc}

    # ---- A：完整、现代、正确的键位 ----
    a_dir = mc / "versions" / "PackA-Alpha"
    a_keys = VANILLA_KEYS_MODERN + MINIMAP_KEYS + RECIPE_KEYS
    write_options(a_dir / "options.txt", a_keys)
    write_options(a_dir / "configureddefaults" / "options.txt", a_keys)
    make_mod_jar(a_dir / "mods" / "xaerominimap-1.0.jar", "xaerominimap", "Xaero's Minimap",
                 {"gui.xaero_open_map": "Open World Map",
                  "gui.xaero_toggle_map": "Toggle Minimap",
                  "gui.xaero_waypoints_key": "Open Waypoint Screen",
                  "gui.xaero_new_waypoint": "New Waypoint"})
    make_mod_jar(a_dir / "mods" / "jei-1.0.jar", "jei", "Just Enough Items",
                 {"key.jei.showRecipe": "Show Recipe",
                  "key.jei.showUses": "Show Uses",
                  "key.jei.toggleOverlay": "Toggle Overlay"},
                 nested=[("ponder", "Ponder", {"ponder.keyinfo.ponder": "Ponder"})])
    (a_dir / "PackA-Alpha.json").write_text(json.dumps({
        "id": "PackA-Alpha", "clientVersion": "1.21.1", "type": "release",
        "libraries": [{"name": "net.neoforged.fancymodloader:loader:4.0.42"}],
    }), encoding="utf-8")
    paths["A"] = a_dir

    # ---- B：同样的 mod，但按键与 A 不同（等待被同步） ----
    b_dir = mc / "versions" / "PackB-Beta"
    b_keys = [(n, _other(v)) for n, v in VANILLA_KEYS_MODERN + MINIMAP_KEYS + RECIPE_KEYS]
    write_options(b_dir / "options.txt", b_keys)
    shutil.copytree(a_dir / "mods", b_dir / "mods")
    (b_dir / "PackB-Beta.json").write_text(json.dumps({
        "id": "PackB-Beta", "clientVersion": "1.21.1", "type": "release",
        "libraries": [{"name": "net.neoforged.fancymodloader:loader:4.0.42"}],
    }), encoding="utf-8")
    paths["B"] = b_dir

    # ---- C：1.12.2，数字键码 ----
    c_dir = mc / "versions" / "PackC-Legacy"
    c_keys = [
        ("key_key.forward", "17"), ("key_key.left", "30"),
        ("key_key.back", "31"), ("key_key.right", "32"),
        ("key_key.jump", "57"), ("key_key.sneak", "42"),
        ("key_key.sprint", "29"), ("key_key.drop", "16"),
        ("key_key.inventory", "18"), ("key_key.attack", "-100"),
        ("key_key.use", "-99"), ("key_key.pickItem", "-98"),
        ("key_gui.xaero_open_map", "50"),
        ("key_key.jei.showRecipe", "19"),
        ("key_key.jei.toggleOverlay", "24"),
    ]
    write_options(c_dir / "options.txt", c_keys)
    make_mod_jar(c_dir / "mods" / "xaerominimap-1.0.jar", "xaerominimap", "Xaero's Minimap",
                 {"gui.xaero_open_map": "Open World Map"})
    make_mod_jar(c_dir / "mods" / "jei-1.0.jar", "jei", "Just Enough Items",
                 {"key.jei.showRecipe": "Show Recipe",
                  "key.jei.toggleOverlay": "Toggle Overlay"})
    (c_dir / "PackC-Legacy.json").write_text(json.dumps({
        "id": "PackC-Legacy", "clientVersion": "1.12.2", "type": "release",
        "libraries": [{"name": "net.minecraftforge:forge:1.12.2-14.23.5.2860"}],
    }), encoding="utf-8")
    paths["C"] = c_dir

    # ---- D：少装了小地图 mod（它的按键不该被写进去） ----
    d_dir = mc / "versions" / "PackD-Delta"
    d_keys = [(n, v) for n, v in VANILLA_KEYS_MODERN + RECIPE_KEYS]
    write_options(d_dir / "options.txt", d_keys)
    make_mod_jar(d_dir / "mods" / "jei-1.0.jar", "jei", "Just Enough Items",
                 {"key.jei.showRecipe": "Show Recipe",
                  "key.jei.showUses": "Show Uses",
                  "key.jei.toggleOverlay": "Toggle Overlay"})
    (d_dir / "PackD-Delta.json").write_text(json.dumps({
        "id": "PackD-Delta", "clientVersion": "1.21.1", "type": "release",
        "libraries": [{"name": "net.neoforged.fancymodloader:loader:4.0.42"}],
    }), encoding="utf-8")
    paths["D"] = d_dir

    # ---- 一个带 BOM 的坏文件，验证修不修得回来 ----
    e_dir = mc / "versions" / "PackE-BOM"
    write_options(e_dir / "options.txt",
                  [(n, _other(v)) for n, v in VANILLA_KEYS_MODERN], bom=True)
    (e_dir / "PackE-BOM.json").write_text(json.dumps({
        "id": "PackE-BOM", "clientVersion": "1.21.1", "type": "release",
        "libraries": [{"name": "net.neoforged.fancymodloader:loader:4.0.42"}],
    }), encoding="utf-8")
    paths["E"] = e_dir

    return paths


def _other(value: str) -> str:
    """给一个不同的键位，保证 B/E 与 A 有差异。"""
    if value == "key.keyboard.unknown":
        return "key.keyboard.unknown"
    if value.startswith("key.mouse."):
        return "key.mouse.right" if "left" in value else "key.mouse.left"
    head, _, mods = value.partition(":")
    mapping = {
        "key.keyboard.w": "key.keyboard.i", "key.keyboard.a": "key.keyboard.j",
        "key.keyboard.s": "key.keyboard.k", "key.keyboard.d": "key.keyboard.l",
        "key.keyboard.space": "key.keyboard.n", "key.keyboard.left.shift": "key.keyboard.m",
        "key.keyboard.left.control": "key.keyboard.comma",
        "key.keyboard.q": "key.keyboard.p", "key.keyboard.e": "key.keyboard.o",
        "key.keyboard.t": "key.keyboard.y", "key.keyboard.tab": "key.keyboard.g",
        "key.keyboard.f5": "key.keyboard.h", "key.keyboard.f2": "key.keyboard.f3",
        "key.keyboard.m": "key.keyboard.z", "key.keyboard.u": "key.keyboard.v",
        "key.keyboard.b": "key.keyboard.c", "key.keyboard.r": "key.keyboard.x",
        "key.keyboard.o": "key.keyboard.f7",
    }
    new = mapping.get(head, head)
    return new + ((":" + mods) if mods else "")


# --------------------------------------------------------------------------
# 各项测试
# --------------------------------------------------------------------------

def test_optionsfile_roundtrip(tmp: Path) -> None:
    section("options.txt 保真读写")
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / "options.txt"
    original = ("lang:zh_cn\r\nfov:0.0\r\n"
                "key_key.forward:key.keyboard.w\r\n"
                "key_key.jei.toggleOverlay:key.keyboard.o:CONTROL\r\n"
                "unknown_line_we_do_not_understand:whatever:with:colons\r\n"
                "soundCategory_master:1.0\r\n")
    path.write_bytes(original.encode("utf-8"))

    options = OptionsFile.load(path)
    eq(options.newline, "\r\n", "识别出 CRLF 换行")
    eq(options.has_bom, False, "没有 BOM")
    eq(options.keybind_count, 2, "数出 2 个按键")
    eq(options.get("unknown_line_we_do_not_understand"), "whatever:with:colons",
       "未知行按第一个冒号切分，值里的冒号保留")
    eq(options.keybinds()["key_key.jei.toggleOverlay"].modifiers, ("CONTROL",),
       "解析出修饰键 CONTROL")
    eq(options.keybinds()["key_key.jei.toggleOverlay"].display(), "Ctrl+O",
       "修饰键显示为 Ctrl+O")

    # 不做任何修改时，写回必须逐字节一致
    options.save()
    eq(path.read_bytes(), original.encode("utf-8"),
       "无改动时写回与原文件逐字节一致")

    # 改一个值，其余保持原样
    options.set("key_key.forward", "key.keyboard.i")
    options.save()
    data = path.read_bytes()
    check(b"\r\n" in data, "改完后仍是 CRLF")
    check(not data.startswith(b"\xef\xbb\xbf"), "改完后仍然没有 BOM")
    check(data.endswith(b"\r\n"), "改完后末尾仍有换行")
    text = data.decode("utf-8")
    check("unknown_line_we_do_not_understand:whatever:with:colons" in text,
          "未知行被原样保留")
    check("key_key.jei.toggleOverlay:key.keyboard.o:CONTROL" in text,
          "修饰键行被原样保留")
    eq(OptionsFile.load(path).get("key_key.forward"), "key.keyboard.i", "新值已写入")

    # 删掉 BOM 的能力
    bom_path = tmp / "bom.txt"
    bom_path.write_bytes(b"\xef\xbb\xbfkey_key.jump:key.keyboard.space\r\n")
    bom = OptionsFile.load(bom_path)
    eq(bom.has_bom, True, "识别出 BOM")
    bom.has_bom = False
    bom.save()
    check(not bom_path.read_bytes().startswith(b"\xef\xbb\xbf"), "BOM 已去除")


def test_keycodes() -> None:
    section("键码解析与跨版本转换")
    eq(KeyCombo.parse("key.keyboard.w").display(), "W", "字母键显示")
    eq(KeyCombo.parse("key.mouse.left").display(), "鼠标左键", "鼠标键显示")
    eq(KeyCombo.parse("key.keyboard.unknown").bound, False, "unknown 视为未绑定")
    eq(KeyCombo.parse("key.keyboard.o:CONTROL").to_options(), "key.keyboard.o:CONTROL",
       "修饰键往返一致")
    eq(KeyCombo.parse("key.keyboard.o:CONTROL:SHIFT").modifiers, ("SHIFT", "CONTROL"),
       "多个修饰键按固定顺序归一")

    # 1.12 数字键码
    eq(legacy_to_named(57), "key.keyboard.space", "旧版 57 -> 空格")
    eq(legacy_to_named(42), "key.keyboard.left.shift", "旧版 42 -> 左Shift")
    eq(legacy_to_named(-100), "key.mouse.left", "旧版 -100 -> 鼠标左键")
    eq(legacy_to_named(-98), "key.mouse.middle", "旧版 -98 -> 鼠标中键")
    eq(legacy_to_named(0), "key.keyboard.unknown", "旧版 0 是「未绑定」")
    eq(named_to_legacy("key.keyboard.space"), 57, "空格 -> 57")
    eq(named_to_legacy("key.mouse.left"), -100, "鼠标左键 -> -100")
    # 关键：数字 0 键和「未绑定」不能混
    eq(named_to_legacy("key.keyboard.0"), 11, "数字 0 键是 11，不是 0")
    check(legacy_to_named(149) is None, "无法确定的旧键码返回 None（不猜）")

    value, warn = convert_value("key.keyboard.space", "legacy")
    eq(value, "57", "命名 -> 旧版数字")
    value, warn = convert_value("key.keyboard.o:CONTROL", "legacy")
    check(value is None and "修饰键" in (warn or ""), "旧版不支持修饰键时明确跳过")
    value, warn = convert_value("57", "named")
    eq(value, "key.keyboard.space", "旧版数字 -> 命名")


def test_modscan(paths: dict) -> None:
    section("Mod 扫描（含 jar-in-jar 与语言文件）")
    result = scan_mods_dir(paths["A"] / "mods")
    ids = {m.mod_id for m in result.mods}
    check("xaerominimap" in ids, "直接读取到 xaerominimap")
    check("jei" in ids, "直接读取到 jei")
    check("ponder" in ids, "递归读到了 jar-in-jar 里的 ponder")

    index = ModIndex()
    index.add_instance("A", result)
    eq(index.display_name("gui.xaero_open_map"), "Open World Map",
       "Xaero 的不规则命名（gui.xaero_*）也能查到显示名")
    eq(index.owner_mod("key.jei.showRecipe"), "jei", "查到按键归属 mod")


def test_naming(paths: dict) -> None:
    section("按键命名解析")
    from mcsync.naming import NamingResolver, prettify_suffix

    result = scan_mods_dir(paths["A"] / "mods")
    index = ModIndex()
    index.add_instance("A", result)
    resolver = NamingResolver(index)

    eq(resolver.resolve("key_key.forward").display, "向前", "原版按键用内置中文名")
    eq(resolver.resolve("key_key.forward").group, "移动", "原版按键归入「移动」分类")
    check(resolver.resolve("key_key.forward").is_vanilla, "原版按键被标记")
    eq(resolver.resolve("key_key.jei.showRecipe", "A").display, "Show Recipe",
       "mod 按键用语言文件里的名字")

    eq(prettify_suffix("irons_spellbooks.spell_wheel", "irons_spellbooks"),
       "Spell wheel", "美化时不会把 spell 误判成 modid 的一部分")
    eq(prettify_suffix("l2mods.dig"), "Dig", "归属未知时丢掉最前面那段")
    eq(prettify_suffix("ponder.keyinfo.ponder", "ponder"), "Ponder",
       "去掉 keyinfo 这类没有信息量的片段")
    eq(prettify_suffix("curios.open.desc", "curios"), "Open",
       "去掉 desc 后缀")

    from mcsync.semantic import family_from_key
    eq(family_from_key("gui.xaero_pac_key_open_menu"), "Xaero 地图",
       "翻译键前缀和 modid 对不上时，靠家族匹配归组")


def test_instance_discovery(paths: dict, tmp: Path) -> None:
    section("实例发现")
    instances = scan_game_dir(paths["mc"], "PCL2")
    names = {i.name for i in instances}
    check({"PackA-Alpha", "PackB-Beta", "PackC-Legacy",
           "PackD-Delta", "PackE-BOM"} <= names,
          "扫出全部 5 个版本实例", f"实际 {sorted(names)}")

    by_name = {i.name: i for i in instances}
    eq(by_name["PackA-Alpha"].mc_version, "1.21.1", "读出 MC 版本")
    eq(by_name["PackA-Alpha"].loader, "NeoForge", "读出加载器")
    eq(by_name["PackC-Legacy"].mc_version, "1.12.2", "读出旧版版本号")
    eq(by_name["PackC-Legacy"].loader, "Forge", "读出 Forge")
    check(by_name["PackA-Alpha"].default_targets,
          "发现 configureddefaults/options.txt 这个附加默认值文件")


def test_conflict_detection() -> None:
    section("冲突检测")
    keybinds = {
        "key_key.forward": KeyCombo.parse("key.keyboard.w"),
        "key_key.left": KeyCombo.parse("key.keyboard.w"),   # 故意撞车
        "key_key.back": KeyCombo.parse("key.keyboard.s"),
        "key_key.jump": KeyCombo.parse("key.keyboard.unknown"),
        "key_key.sneak": KeyCombo.parse("key.keyboard.unknown"),
    }
    conflicts = find_conflicts(keybinds)
    eq(len(conflicts), 1, "找出 1 处冲突")
    eq(len(conflicts[0].entries), 2, "冲突涉及 2 个按键")


def test_full_sync(paths: dict, tmp: Path) -> None:
    section("端到端同步")
    app = App(data_dir=tmp / "data")
    instances = app.discover_instances(
        do_drive_scan=False, progress=None)
    # scan_game_dir 直接产出的实例更可控
    from mcsync.instances import scan_game_dir as sgd
    instances = sgd(paths["mc"], "PCL2")
    app.instances = instances
    by_name = {i.name: i for i in instances}

    app.ensure_mod_index(instances)

    # 1) 从 A 抓一份主配置
    profile_a = app.capture_profile(by_name["PackA-Alpha"], "测试主配置")
    eq(profile_a.binding_count, len(VANILLA_KEYS_MODERN + MINIMAP_KEYS + RECIPE_KEYS),
       "抓到的按键数量正确")

    # 2) 对比表：B 应该有差异，C 因为键码风格不同也有差异
    table = app.make_diff(profile_a,
                          [by_name["PackB-Beta"], by_name["PackD-Delta"]])
    row_map = {r.binding_name: r for r in table.rows}
    forward = row_map["key_key.forward"]
    eq(forward.kind_for(by_name["PackB-Beta"].key), ChangeKind.DIFFERS,
       "B 的 forward 判定为「不一致」")
    eq(forward.kind_for(by_name["PackD-Delta"].key), ChangeKind.SAME,
       "D 的 forward 判定为「一致」")
    check(row_map["key_gui.xaero_open_map"].kind_for(by_name["PackD-Delta"].key)
          == ChangeKind.ONLY_IN_PROFILE,
          "D 没装小地图 mod，该按键判定为「目标没有此按键」")

    # 3) 生成并执行计划
    targets = [by_name["PackB-Beta"], by_name["PackC-Legacy"], by_name["PackD-Delta"]]
    plan = app.make_plan(profile_a, targets)
    total = plan.total_changes
    check(total > 0, "生成了变更计划")

    results = app.run_plan(plan, do_backup=True)
    check(all(r.ok for r in results), "全部写入成功",
          "; ".join(f"{r.instance_name}:{r.error}" for r in results if not r.ok))

    # 4) 校验 B 真的被改成了 A 的值
    b_after = OptionsFile.load(by_name["PackB-Beta"].options_path)
    b_keys = b_after.keybinds()
    a_keys = OptionsFile.load(by_name["PackA-Alpha"].options_path).keybinds()
    for name in VANILLA_KEYS_MODERN + MINIMAP_KEYS + RECIPE_KEYS:
        binding = name[0]
        if binding in a_keys:
            eq(b_keys[binding].to_options(), a_keys[binding].to_options(),
               f"B 的 {binding} 已与 A 一致")
    check(b_after.newline == "\r\n" and not b_after.has_bom,
          "B 写回后仍是 CRLF 且无 BOM")

    # 5) D 不该被写入它没有的小地图按键
    d_after = OptionsFile.load(by_name["PackD-Delta"].options_path)
    check("key_gui.xaero_open_map" not in d_after.keybinds(),
          "D 缺少小地图 mod，没有被写入该按键（否则会被游戏抹掉）")

    # 6) C 是 1.12，应该被写成数字键码
    c_after = OptionsFile.load(by_name["PackC-Legacy"].options_path)
    c_raw = c_after.keybind_raw()
    eq(c_raw.get("key_key.forward"), "17", "C 的 forward 写成了旧版数字 17")
    eq(c_raw.get("key_key.sneak"), "42", "C 的 sneak 写成了旧版数字 42")
    eq(c_raw.get("key_key.attack"), "-100", "C 的鼠标左键写成了 -100")
    eq(c_after.code_style(), "legacy", "C 仍然是旧版键码风格")
    # 带修饰键的按键在旧版无法表达，应当被跳过而不是写脏数据
    check("key_key.jei.toggleOverlay" not in
          [c.binding_name for c in plan.plans[1].keybind_changes],
          "旧版无法表达修饰键组合时跳过该按键")

    # 7) 备份存在且可还原
    records = app.backup_manager.list()
    check(len(records) >= 1, "产生了备份")
    before_restore = by_name["PackB-Beta"].options_path.read_bytes()
    restored, errors = app.backup_manager.restore(records[-1])
    check(restored >= 1 and not errors, "还原成功", str(errors))
    check(by_name["PackB-Beta"].options_path.read_bytes() != before_restore,
          "还原后 B 的文件确实变了（说明还原生效）")

    # 8) 幂等：再同步一次应该没有变更
    plan2 = app.make_plan(profile_a, [by_name["PackA-Alpha"]])
    eq(plan2.total_changes, 0, "对已经是主配置的实例再同步，变更为 0")


def test_options_and_defaults(paths: dict, tmp: Path) -> None:
    section("其他设置同步 + 默认值文件写入")
    app = App(data_dir=tmp / "data2")
    from mcsync.instances import scan_game_dir as sgd
    instances = sgd(paths["mc"], "PCL2")
    app.instances = instances
    by_name = {i.name: i for i in instances}
    app.ensure_mod_index(instances)

    profile = app.capture_profile(by_name["PackA-Alpha"], "含设置的主配置")
    check("fov" in profile.options, "抓取时带上了其他设置")
    profile.options["fov"] = "0.7"
    profile.options["guiScale"] = "2"

    app.settings.sync_options = True
    app.settings.option_names = ["fov", "guiScale", "resourcePacks", "tutorialStep"]
    app.settings.write_default_targets = True

    plan = app.make_plan(profile, [by_name["PackB-Beta"]])
    names = {c.name for p in plan.plans for c in p.option_changes}
    check("fov" in names, "fov 被列入变更")
    check("resourcePacks" not in names, "resourcePacks 属于实例相关项，被排除")
    check("tutorialStep" not in names, "tutorialStep 属于实例相关项，被排除")

    results = app.run_plan(plan, do_backup=True)
    check(all(r.ok for r in results), "设置与默认值文件都写入成功",
          "; ".join(f"{r.path}:{r.error}" for r in results if not r.ok))

    b_after = OptionsFile.load(by_name["PackB-Beta"].options_path)
    eq(b_after.get("fov"), "0.7", "B 的 fov 已同步")
    check(b_after.keybinds()["key_key.forward"].to_options() == "key.keyboard.w",
          "选项同步时按键也一起同步了")

    defaults = by_name["PackB-Beta"].game_dir / "configureddefaults" / "options.txt"
    if defaults.is_file():
        d = OptionsFile.load(defaults)
        eq(d.get("fov"), "0.7", "默认值文件里的 fov 也被同步（整合包重置后仍生效）")


def test_bom_repair(paths: dict, tmp: Path) -> None:
    section("带 BOM 的文件修复")
    app = App(data_dir=tmp / "data3")
    from mcsync.instances import scan_game_dir as sgd
    instances = sgd(paths["mc"], "PCL2")
    app.instances = instances
    by_name = {i.name: i for i in instances}
    app.ensure_mod_index(instances)

    e_path = by_name["PackE-BOM"].options_path
    check(OptionsFile.load(e_path).has_bom, "E 的文件确实带 BOM")

    profile = app.capture_profile(by_name["PackA-Alpha"], "修复用")
    plan = app.make_plan(profile, [by_name["PackE-BOM"]])
    check(any("BOM" in w for p in plan.plans for w in p.warnings),
          "计划里给出了 BOM 警告")
    results = app.run_plan(plan, do_backup=True)
    check(all(r.ok for r in results), "写入成功")
    check(not OptionsFile.load(e_path).has_bom, "BOM 已被修掉")


def test_backup_manager(tmp: Path) -> None:
    section("备份管理")
    tmp.mkdir(parents=True, exist_ok=True)
    root = tmp / "bk"
    manager = BackupManager(root, keep=3)
    source = tmp / "src.txt"
    target = tmp / "dst.txt"
    source.write_text("v1", encoding="utf-8")
    target.write_text("original", encoding="utf-8")

    record = manager.create([(target, "实例1", "options")], label="同步前")
    check(record is not None, "创建了备份")
    eq(record.file_count, 1, "备份里 1 个文件")

    target.write_text("changed", encoding="utf-8")
    restored, errors = manager.restore(record)
    eq(restored, 1, "还原 1 个文件")
    eq(errors, [], "还原没有报错")
    eq(target.read_text(encoding="utf-8"), "original", "内容已还原")

    for i in range(5):
        manager.create([(target, "x", "options")], label=f"批量{i}")
    check(len(manager.list()) <= 3, "只保留最近 3 份备份")


def test_profile_json(tmp: Path) -> None:
    section("配置 JSON 读写")
    tmp.mkdir(parents=True, exist_ok=True)
    profile = Profile(name="我的键位")
    profile.set("key_key.forward", KeyCombo.parse("key.keyboard.w"))
    profile.set("key_key.jei.toggleOverlay", KeyCombo.parse("key.keyboard.o:CONTROL"))
    profile.options["fov"] = "0.5"

    path = tmp / "p.json"
    profile.save(path)
    loaded = Profile.load(path)
    eq(loaded.name, "我的键位", "名字保留")
    eq(loaded.keybinds["key_key.forward"].to_options(), "key.keyboard.w", "按键保留")
    eq(loaded.keybinds["key_key.jei.toggleOverlay"].modifiers, ("CONTROL",),
       "修饰键保留")
    eq(loaded.options["fov"], "0.5", "其他设置保留")

    try:
        Profile.load(_write_bad(tmp))
        check(False, "应该拒绝不是本工具的配置文件")
    except ValueError:
        check(True, "拒绝不是本工具的配置文件")


def _write_bad(tmp: Path) -> Path:
    path = tmp / "bad.json"
    path.write_text('{"format": "something-else", "name": "x"}', encoding="utf-8")
    return path


def test_config_file_scan(paths: dict) -> None:
    section("模组配置文件扫描")
    from mcsync.configfiles import scan_config_dir

    game_dir = paths["A"]
    cfg = game_dir / "config" / "somemod.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({
        "toggle_key": "key.keyboard.g",
        "openKey": "KEY_H",
        "unrelated": "hello world",
    }), encoding="utf-8")

    candidates = scan_config_dir(game_dir)
    rels = {c.relative_path for c in candidates}
    check(any("somemod.json" in r for r in rels),
          "找到含疑似快捷键的配置文件", f"实际 {sorted(rels)[:5]}")
    hit = next((c for c in candidates if "somemod.json" in c.relative_path), None)
    if hit:
        check(len(hit.key_fields) >= 2, "识别出至少 2 个快捷键字段",
              str(hit.key_fields))


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def test_manual_change_baseline(paths: dict, tmp: Path) -> None:
    """同步基线：用户在游戏里解绑/改过的键，不该被主配置盖回去。"""
    section("手动改动保护（同步基线）")
    from mcsync.instances import scan_game_dir as sgd
    from mcsync.sync import SyncPolicy

    app = App(data_dir=tmp / "state-data")
    instances = sgd(paths["mc"], "PCL2")
    app.instances = instances
    by_name = {i.name: i for i in instances}
    src, dst = by_name["PackA-Alpha"], by_name["PackB-Beta"]
    b_path = dst.options_path

    profile = app.capture_profile(src, "基线测试")

    # 先把 B 的截图键改成别的，确保第一次同步真的会动它
    start = OptionsFile.load(b_path)
    start.set("key_key.screenshot", "key.keyboard.f3")
    start.save()

    plan = app.make_plan(profile, [dst])
    changed = {c.binding_name for c in plan.plans[0].keybind_changes}
    check("key_key.screenshot" in changed, "第一次同步会按主配置改回截图键")
    results = app.run_plan(plan, do_backup=False)
    check(all(r.ok for r in results), "第一次同步写入成功",
          "; ".join(r.error for r in results if not r.ok))
    check(app.sync_state().has_snapshot(dst.key), "同步后留下了基线")
    eq(OptionsFile.load(b_path).keybinds()["key_key.screenshot"].to_options(),
       "key.keyboard.f2", "截图键已被同步成主配置的值")

    # 模拟用户在游戏里把截图键解绑、并把丢弃键改成 G
    raw = b_path.read_bytes().decode("utf-8")
    raw = raw.replace("key_key.screenshot:key.keyboard.f2",
                      "key_key.screenshot:key.keyboard.unknown")
    raw = raw.replace("key_key.drop:key.keyboard.q", "key_key.drop:key.keyboard.g")
    b_path.write_bytes(raw.encode("utf-8"))

    # 再同步：这两条都该被跳过，而不是被盖回去
    plan2 = app.make_plan(profile, [dst])
    changed2 = {c.binding_name for c in plan2.plans[0].keybind_changes}
    reasons = {s.binding_name: s.reason for s in plan2.plans[0].skipped}
    check("key_key.screenshot" not in changed2, "解绑过的截图键没有被重新绑上")
    check("key_key.drop" not in changed2, "手动改过的丢弃键没有被盖回去")
    check("key_key.screenshot" in reasons and "保留" in reasons["key_key.screenshot"],
          "跳过时给出了原因", reasons.get("key_key.screenshot", ""))

    results2 = app.run_plan(plan2, do_backup=False)
    check(all(r.ok for r in results2), "第二次同步写入成功")
    now = OptionsFile.load(b_path).keybinds()
    eq(now["key_key.screenshot"].to_options(), "key.keyboard.unknown",
       "截图键保持未绑定")
    eq(now["key_key.drop"].to_options(), "key.keyboard.g", "丢弃键保持 G")

    # 关掉这个策略 -> 强制对齐主配置
    forced = SyncPolicy(**{**app.make_policy().__dict__,
                           "respect_manual_changes": False})
    plan3 = app.make_plan(profile, [dst], policy=forced)
    changed3 = {c.binding_name for c in plan3.plans[0].keybind_changes}
    check("key_key.screenshot" in changed3, "关掉策略后会强制绑回主配置的值")

    # 重置基线 -> 同样强制对齐
    app.reset_sync_state()
    plan4 = app.make_plan(profile, [dst])
    changed4 = {c.binding_name for c in plan4.plans[0].keybind_changes}
    check("key_key.screenshot" in changed4, "重置基线后会强制对齐")


def test_state_file(tmp: Path) -> None:
    section("同步基线的读写")
    from mcsync.state import SyncState

    path = tmp / "state-test" / "sync_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state = SyncState.load(path)
    check(not state.has_snapshot("inst"), "空状态下没有基线")
    check(not state.manually_changed("inst", "key_key.jump", "key.keyboard.w"),
          "没有基线时不判定为「被改过」")

    state.record("inst", {"key_key.jump": "key.keyboard.space"})
    state.save()
    eq(path.is_file(), True, "基线落盘成功")

    again = SyncState.load(path)
    check(again.has_snapshot("inst"), "重新载入后基线还在")
    check(not again.manually_changed("inst", "key_key.jump", "key.keyboard.space"),
          "没变过 -> 不算手动改动")
    check(again.manually_changed("inst", "key_key.jump", "key.keyboard.unknown"),
          "变成未绑定 -> 判定为手动改动")
    check(not again.manually_changed("inst", "key_key.other", "key.keyboard.g"),
          "基线里没有的按键 -> 不判定为手动改动")
    check(again.forget("inst") and not again.has_snapshot("inst"),
          "可以忘掉某个实例的基线")

    broken = tmp / "state-test" / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    check(not SyncState.load(broken).instances, "坏文件不会抛异常，当成空基线")


def run_selftest(verbose: bool = False, work_dir: Path | None = None) -> int:
    global _PASS, _FAIL, _VERBOSE
    _PASS = 0
    _FAIL = []
    _VERBOSE = verbose

    print("MCKeyBinder 按键同步器 —— 合成数据自测")
    print("=" * 64)

    # 有些环境（沙箱、受限权限）不允许往系统临时目录里再建子目录，
    # 所以允许显式指定工作目录；默认优先用项目内的 data/.selftest。
    if work_dir is None:
        project_local = Path(__file__).resolve().parent.parent / "data" / ".selftest"
        try:
            project_local.mkdir(parents=True, exist_ok=True)
            probe = project_local / ".probe"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
            work_dir = project_local
        except OSError:
            work_dir = None

    if work_dir is not None:
        work_dir = Path(work_dir)
        shutil.rmtree(work_dir, ignore_errors=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        exit_code = _run_all(work_dir)
        shutil.rmtree(work_dir, ignore_errors=True)
        return exit_code

    with tempfile.TemporaryDirectory(prefix="mcsync-selftest-") as temp:
        return _run_all(Path(temp))


def _run_all(tmp: Path) -> int:
    fixture_root = tmp / "fixture"
    paths = build_fixture(fixture_root)
    print(f"合成实例目录：{fixture_root}")

    test_optionsfile_roundtrip(tmp / "unit")
    test_keycodes()
    test_conflict_detection()
    test_backup_manager(tmp / "backup-test")
    test_profile_json(tmp / "profile-test")
    test_modscan(paths)
    test_naming(paths)
    test_instance_discovery(paths, tmp)
    test_config_file_scan(paths)
    test_full_sync(paths, tmp)
    test_options_and_defaults(paths, tmp)
    test_bom_repair(paths, tmp)
    test_state_file(tmp / "state-test")
    test_manual_change_baseline(paths, tmp)

    print("\n" + "=" * 64)
    if _FAIL:
        print(f"结果：通过 {_PASS} 项，失败 {len(_FAIL)} 项\n")
        for item in _FAIL:
            print(f"  ✗ {item}")
        return 1
    print(f"结果：全部 {_PASS} 项检查通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_selftest("-v" in sys.argv or "--verbose" in sys.argv))
