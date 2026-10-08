# -*- coding: utf-8 -*-
"""MC 1.12.2 及更早（LWJGL2 数字键码）<-> MC 1.13+（命名键码）。

数据来源（已逐条核对）：

* https://minecraft.wiki/w/Key_codes —— 1.13+ 命名键码全集
* https://minecraft.wiki/w/Java_Edition_pre-flattening_data_values#Key_codes
  —— 1.12.2 ``options.txt`` 里的数字含义（section 7 键盘 / section 8 鼠标）
* LWJGL2 ``org.lwjgl.input.Keyboard`` 的 ``KEY_*`` 常量

几个**极易搞错**的点，本表已按正确语义处理：

1. **鼠标键在 1.12 里是负数**：左 ``-100`` / 右 ``-99`` / 中 ``-98``。
   ``key_key.drop:211`` 里的 211 不是鼠标键，而是 **LWJGL2 的 Delete 键**
   （``KEY_DELETE = 0xD3 = 211``）。
2. **旧版 ``0`` 表示「未绑定」**，而新版的 ``key.keyboard.0`` 表示**数字 0 键**
   （旧版数字 0 键是 ``11``）。两者语义完全相反，必须分开处理。
3. **小键盘小数点**：旧版是 ``KEY_DECIMAL = 83``，1.13~1.25 的名字是
   ``key.keyboard.keypad.period``，26.3 起才改成 ``key.keyboard.keypad.decimal``。
   本表取覆盖面更广的 ``keypad.period``。
4. **F11/F12 是 87/88**（不与 F1–F10 连续）；**F19 是 113**（中间被 KANA=112 占用）。
"""

from __future__ import annotations

#: 旧版把「未绑定」写作 0
UNBOUND_LEGACY = 0

#: 现代命名键码 -> 旧版数字键码（严格双射，可直接反查）
NAMED_TO_LEGACY: dict[str, int] = {
    # 功能键行 / 数字行
    "key.keyboard.escape": 1,
    "key.keyboard.1": 2,
    "key.keyboard.2": 3,
    "key.keyboard.3": 4,
    "key.keyboard.4": 5,
    "key.keyboard.5": 6,
    "key.keyboard.6": 7,
    "key.keyboard.7": 8,
    "key.keyboard.8": 9,
    "key.keyboard.9": 10,
    "key.keyboard.0": 11,
    "key.keyboard.minus": 12,
    "key.keyboard.equal": 13,
    "key.keyboard.backspace": 14,
    "key.keyboard.tab": 15,
    # 字母区（物理位置键码，与键盘布局无关）
    "key.keyboard.q": 16,
    "key.keyboard.w": 17,
    "key.keyboard.e": 18,
    "key.keyboard.r": 19,
    "key.keyboard.t": 20,
    "key.keyboard.y": 21,
    "key.keyboard.u": 22,
    "key.keyboard.i": 23,
    "key.keyboard.o": 24,
    "key.keyboard.p": 25,
    "key.keyboard.left.bracket": 26,
    "key.keyboard.right.bracket": 27,
    "key.keyboard.enter": 28,
    "key.keyboard.left.control": 29,
    "key.keyboard.a": 30,
    "key.keyboard.s": 31,
    "key.keyboard.d": 32,
    "key.keyboard.f": 33,
    "key.keyboard.g": 34,
    "key.keyboard.h": 35,
    "key.keyboard.j": 36,
    "key.keyboard.k": 37,
    "key.keyboard.l": 38,
    "key.keyboard.semicolon": 39,
    "key.keyboard.apostrophe": 40,
    "key.keyboard.grave.accent": 41,
    "key.keyboard.left.shift": 42,
    "key.keyboard.backslash": 43,
    "key.keyboard.z": 44,
    "key.keyboard.x": 45,
    "key.keyboard.c": 46,
    "key.keyboard.v": 47,
    "key.keyboard.b": 48,
    "key.keyboard.n": 49,
    "key.keyboard.m": 50,
    "key.keyboard.comma": 51,
    "key.keyboard.period": 52,
    "key.keyboard.slash": 53,
    "key.keyboard.right.shift": 54,
    # 小键盘
    "key.keyboard.keypad.multiply": 55,
    "key.keyboard.left.alt": 56,
    "key.keyboard.space": 57,
    "key.keyboard.caps.lock": 58,
    # 功能键
    "key.keyboard.f1": 59,
    "key.keyboard.f2": 60,
    "key.keyboard.f3": 61,
    "key.keyboard.f4": 62,
    "key.keyboard.f5": 63,
    "key.keyboard.f6": 64,
    "key.keyboard.f7": 65,
    "key.keyboard.f8": 66,
    "key.keyboard.f9": 67,
    "key.keyboard.f10": 68,
    "key.keyboard.num.lock": 69,
    "key.keyboard.scroll.lock": 70,
    "key.keyboard.keypad.7": 71,
    "key.keyboard.keypad.8": 72,
    "key.keyboard.keypad.9": 73,
    "key.keyboard.keypad.subtract": 74,
    "key.keyboard.keypad.4": 75,
    "key.keyboard.keypad.5": 76,
    "key.keyboard.keypad.6": 77,
    "key.keyboard.keypad.add": 78,
    "key.keyboard.keypad.1": 79,
    "key.keyboard.keypad.2": 80,
    "key.keyboard.keypad.3": 81,
    "key.keyboard.keypad.0": 82,
    # 1.13~1.25 叫 keypad.period；26.3+ 才叫 keypad.decimal
    "key.keyboard.keypad.period": 83,
    "key.keyboard.f11": 87,   # 注意不是 89
    "key.keyboard.f12": 88,
    # 高位功能键 / 日文与 NEC 键
    "key.keyboard.f13": 100,
    "key.keyboard.f14": 101,
    "key.keyboard.f15": 102,
    "key.keyboard.f16": 103,
    "key.keyboard.f17": 104,
    "key.keyboard.f18": 105,
    "key.keyboard.f19": 113,  # 注意不是 106
    "key.keyboard.lang1": 112,
    "key.keyboard.convert": 121,
    "key.keyboard.noconvert": 123,
    "key.keyboard.international3": 125,
    "key.keyboard.keypad.equal": 141,
    "key.keyboard.circumflex": 144,
    "key.keyboard.at": 145,
    "key.keyboard.colon": 146,
    "key.keyboard.underline": 147,
    "key.keyboard.kanji": 148,
    "key.keyboard.keypad.enter": 156,
    "key.keyboard.right.control": 157,
    "key.keyboard.keypad.comma": 179,
    "key.keyboard.keypad.divide": 181,
    "key.keyboard.sys.req": 183,
    "key.keyboard.right.alt": 184,
    # 导航 / 编辑区
    "key.keyboard.pause": 197,
    "key.keyboard.home": 199,
    "key.keyboard.up": 200,
    "key.keyboard.page.up": 201,
    "key.keyboard.left": 203,
    "key.keyboard.right": 205,
    "key.keyboard.end": 207,
    "key.keyboard.down": 208,
    "key.keyboard.page.down": 209,
    "key.keyboard.insert": 210,
    "key.keyboard.delete": 211,
    # 系统键
    "key.keyboard.left.win": 219,
    "key.keyboard.right.win": 220,
    "key.keyboard.application": 221,
    "key.keyboard.power": 222,
    "key.keyboard.sleep": 223,
    # 鼠标（旧版用负数，Minecraft 加了 -100 偏移）
    "key.mouse.left": -100,
    "key.mouse.right": -99,
    "key.mouse.middle": -98,
    "key.mouse.4": -97,
    "key.mouse.5": -96,
    "key.mouse.6": -95,
    "key.mouse.7": -94,
    "key.mouse.8": -93,
}

#: 反向表（源表是双射，可安全反查）
LEGACY_TO_NAMED: dict[int, str] = {v: k for k, v in NAMED_TO_LEGACY.items()}

#: 同一个旧键码在新版里可能写成不同名字（操作系统 / 版本差异）。
#: 这些别名**不放进主表**，否则反查会互相覆盖。
ALIASES: dict[str, str] = {
    # 43 在 Windows 上 26.3 起改用 world.1；ISO 反斜杠与 ANSI 反斜杠在旧版无法区分
    "key.keyboard.world.1": "key.keyboard.backslash",
    # 26.3+ 的小键盘小数点
    "key.keyboard.keypad.decimal": "key.keyboard.keypad.period",
    # KANA 的另一种写法
    "key.keyboard.international2": "key.keyboard.lang1",
    # 26.3+ 对 CONVERT / NOCONVERT 的改名
    "key.keyboard.international4": "key.keyboard.convert",
    "key.keyboard.international5": "key.keyboard.noconvert",
}

#: 已知无法可靠转换的旧键码 -> 原因。遇到时**跳过并报警**，不写猜测值。
UNCERTAIN: dict[int, str] = {
    149: "LWJGL2 KEY_STOP：GLFW / SDL3 键名表里都没有可验证的对应项",
    150: "LWJGL2 KEY_AX（日本 AX 键盘规格）：现代键名表无对应项",
    151: "LWJGL2 KEY_UNLABELED（J3100 键盘无标签键）：现代键名表无对应项",
}

#: 需要按目标版本二选一的键（目前只影响转换表的取值，不阻塞同步）
VERSION_DEPENDENT: dict[str, str] = {
    "key.keyboard.keypad.period":
        "1.13~1.25 用 keypad.period；26.3 起改名为 keypad.decimal。本表取前者。",
}


def legacy_to_named(code: int) -> str | None:
    """旧版数字键码 -> 现代命名键码。无法确定时返回 ``None``。"""
    from .keycodes import UNBOUND

    if code == UNBOUND_LEGACY:
        # 旧版的 0 是「未绑定」；注意新版 key.keyboard.0 是数字 0 键，语义相反
        return UNBOUND
    if code in UNCERTAIN:
        return None
    return LEGACY_TO_NAMED.get(code)


def named_to_legacy(code: str) -> int | None:
    """现代命名键码 -> 旧版数字键码。无对应时返回 ``None``。"""
    from .keycodes import UNBOUND

    if code == UNBOUND:
        return UNBOUND_LEGACY
    if code in ALIASES:
        code = ALIASES[code]
    return NAMED_TO_LEGACY.get(code)


def convert_value(value: str, target_style: str) -> tuple[str | None, str | None]:
    """把按键值在 ``named`` / ``legacy`` 两种风格之间转换。

    返回 ``(新值, 警告)``；无法转换时新值为 ``None``。
    """
    from .keycodes import KeyCombo

    combo = KeyCombo.parse(value)

    if target_style == "legacy":
        if combo.modifiers:
            # 旧版 options.txt 只能存「单个物理键」，表达不了修饰键组合。
            # Advanced KeyBindings / Amecs 之类曾用别的写法，但那是 mod 私有格式，
            # 直接写 vanilla 格式会被忽略甚至弄坏，所以宁可跳过并告知用户。
            return None, "1.12 及更早不支持修饰键组合"
        if not combo.bound:
            return str(UNBOUND_LEGACY), None
        legacy = named_to_legacy(combo.code)
        if legacy is None:
            return None, f"「{combo.display()}」在旧版键码表里没有对应项"
        return str(legacy), None

    # target_style == "named"
    head = (value or "").split(":", 1)[0].strip()
    if head and head.lstrip("-").isdigit():
        num = int(head)
        named = legacy_to_named(num)
        if named is None:
            reason = UNCERTAIN.get(num, f"未知的旧版键码 {num}")
            return None, reason
        return KeyCombo(named).to_options(), None
    return combo.to_options(), None
