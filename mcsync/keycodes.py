# -*- coding: utf-8 -*-
"""键码（key code）模型：解析、规范化、显示、跨版本转换。

``options.txt`` 里一行按键长这样::

    key_key.jei.toggleOverlay:key.keyboard.o:CONTROL

拆成三部分：

* ``key_key.jei.toggleOverlay`` —— 绑定名（binding name）= ``key_`` + 翻译键
* ``key.keyboard.o``             —— 键码
* ``CONTROL``                    —— 修饰键（可有多个，用 ``:`` 分隔）

旧版（1.12.2 及更早）的键码是数字（LWJGL2），例如 ``key_key.jump:57``。
本模块统一用现代命名键码做内部表示，读写时按目标版本格式转换。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

# --------------------------------------------------------------------------
# 修饰键
# --------------------------------------------------------------------------

#: Forge / Amecs / ModernKeyBinding 使用的修饰键名字，顺序固定用于稳定输出
MODIFIER_ORDER: tuple[str, ...] = ("SHIFT", "CONTROL", "ALT", "WIN")

_MODIFIER_ALIASES: dict[str, str] = {
    "SHIFT": "SHIFT",
    "CONTROL": "CONTROL",
    "CTRL": "CONTROL",
    "ALT": "ALT",
    "META": "WIN",
    "WIN": "WIN",
    "SUPER": "WIN",
    "COMMAND": "WIN",
    "CMD": "WIN",
    "OPTION": "ALT",
}

UNBOUND = "key.keyboard.unknown"


def normalise_modifier(token: str) -> str | None:
    """把修饰键写法归一化；无法识别时返回 ``None``。"""
    return _MODIFIER_ALIASES.get(token.strip().upper())


# --------------------------------------------------------------------------
# 键码显示名
# --------------------------------------------------------------------------

#: 特殊键的界面显示名（中文优先，符合 MC 中文客户端的叫法）
_SPECIAL_DISPLAY: dict[str, str] = {
    UNBOUND: "未绑定",
    "key.keyboard.space": "空格",
    "key.keyboard.tab": "Tab",
    "key.keyboard.enter": "回车",
    "key.keyboard.escape": "Esc",
    "key.keyboard.backspace": "退格",
    "key.keyboard.delete": "Delete",
    "key.keyboard.insert": "Insert",
    "key.keyboard.home": "Home",
    "key.keyboard.end": "End",
    "key.keyboard.page.up": "Page Up",
    "key.keyboard.page.down": "Page Down",
    "key.keyboard.caps.lock": "大写锁定",
    "key.keyboard.num.lock": "数字锁定",
    "key.keyboard.scroll.lock": "滚动锁定",
    "key.keyboard.print.screen": "Print Screen",
    "key.keyboard.pause": "Pause",
    "key.keyboard.menu": "菜单键",
    "key.keyboard.up": "↑",
    "key.keyboard.down": "↓",
    "key.keyboard.left": "←",
    "key.keyboard.right": "→",
    "key.keyboard.left.shift": "左Shift",
    "key.keyboard.right.shift": "右Shift",
    "key.keyboard.left.control": "左Ctrl",
    "key.keyboard.right.control": "右Ctrl",
    "key.keyboard.left.alt": "左Alt",
    "key.keyboard.right.alt": "右Alt",
    "key.keyboard.left.win": "左Win",
    "key.keyboard.right.win": "右Win",
    "key.keyboard.left.option": "左Option",
    "key.keyboard.right.option": "右Option",
    "key.keyboard.left.command": "左Command",
    "key.keyboard.right.command": "右Command",
    "key.keyboard.comma": ",",
    "key.keyboard.period": ".",
    "key.keyboard.slash": "/",
    "key.keyboard.semicolon": ";",
    "key.keyboard.apostrophe": "'",
    "key.keyboard.grave.accent": "`",
    "key.keyboard.left.bracket": "[",
    "key.keyboard.right.bracket": "]",
    "key.keyboard.backslash": "\\",
    "key.keyboard.minus": "-",
    "key.keyboard.equal": "=",
    "key.keyboard.world.1": "World 1",
    "key.keyboard.world.2": "World 2",
    "key.mouse.left": "鼠标左键",
    "key.mouse.right": "鼠标右键",
    "key.mouse.middle": "鼠标中键",
    "key.mouse.4": "鼠标4",
    "key.mouse.5": "鼠标5",
    "key.mouse.6": "鼠标6",
    "key.mouse.7": "鼠标7",
    "key.mouse.8": "鼠标8",
}

_NUMPAD_DISPLAY: dict[str, str] = {
    "keypad.0": "小键盘0",
    "keypad.1": "小键盘1",
    "keypad.2": "小键盘2",
    "keypad.3": "小键盘3",
    "keypad.4": "小键盘4",
    "keypad.5": "小键盘5",
    "keypad.6": "小键盘6",
    "keypad.7": "小键盘7",
    "keypad.8": "小键盘8",
    "keypad.9": "小键盘9",
    "keypad.decimal": "小键盘.",
    "keypad.divide": "小键盘/",
    "keypad.multiply": "小键盘*",
    "keypad.subtract": "小键盘-",
    "keypad.add": "小键盘+",
    "keypad.enter": "小键盘回车",
    "keypad.equal": "小键盘=",
}


def key_display(code: str) -> str:
    """把单个键码变成人类可读的短名。"""
    if not code:
        return "未绑定"
    if code in _SPECIAL_DISPLAY:
        return _SPECIAL_DISPLAY[code]
    for prefix in ("key.keyboard.", "key.mouse."):
        if code.startswith(prefix):
            tail = code[len(prefix):]
            if prefix == "key.keyboard.":
                if tail in _NUMPAD_DISPLAY:
                    return _NUMPAD_DISPLAY[tail]
                if len(tail) == 1:
                    return tail.upper()
                if tail.startswith("f") and tail[1:].isdigit():
                    return "F" + tail[1:]
                if tail.isdigit():
                    return tail
            else:
                return "鼠标" + tail
            return tail
    # 未知命名空间：原样显示但去掉前缀
    return code


# --------------------------------------------------------------------------
# KeyCombo
# --------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class KeyCombo:
    """一个按键绑定：键码 + 修饰键组合。"""

    code: str = UNBOUND
    modifiers: tuple[str, ...] = ()

    # -- 构造 ------------------------------------------------------------
    @classmethod
    def parse(cls, raw: str | None) -> "KeyCombo":
        """解析 ``options.txt`` 里按键行冒号右侧的内容。

        ``key.keyboard.o:CONTROL``       -> code=key.keyboard.o, modifiers=('CONTROL',)
        ``key.keyboard.o:CONTROL:SHIFT`` -> 两个修饰键
        ``57``                           -> 旧版数字键码，自动转成命名键码
        """
        if raw is None:
            return cls()
        text = raw.strip()
        if not text:
            return cls()

        parts = text.split(":")
        code = parts[0].strip()
        modifiers: list[str] = []
        for token in parts[1:]:
            mod = normalise_modifier(token)
            if mod is None:
                # 无法识别的尾巴：当作键码的一部分保留，避免丢信息
                code = code + ":" + token
            elif mod not in modifiers:
                modifiers.append(mod)

        code = normalise_code(code)
        return cls(code=code, modifiers=tuple(sorted(modifiers, key=_mod_sort_key)))

    # -- 输出 ------------------------------------------------------------
    def to_options(self) -> str:
        """还原成 ``options.txt`` 里的写法。"""
        out = self.code
        for mod in self.modifiers:
            out += ":" + mod
        return out

    # -- 查询 ------------------------------------------------------------
    @property
    def bound(self) -> bool:
        """是否真的绑定了键（未绑定为空）。"""
        return bool(self.code) and self.code != UNBOUND

    @property
    def is_mouse(self) -> bool:
        return self.code.startswith("key.mouse.")

    def display(self, separator: str = "+") -> str:
        """界面显示名，例如 ``Ctrl+O``、``鼠标左键``。"""
        if not self.bound:
            return "未绑定"
        name = key_display(self.code)
        if not self.modifiers:
            return name
        prefix = separator.join(_MODIFIER_DISPLAY[m] for m in self.modifiers)
        return f"{prefix}{separator}{name}"

    def with_modifiers(self, modifiers: Iterable[str]) -> "KeyCombo":
        return KeyCombo(self.code, tuple(sorted(set(modifiers), key=_mod_sort_key)))

    def without_modifiers(self) -> "KeyCombo":
        return KeyCombo(self.code, ())


_MODIFIER_DISPLAY = {
    "SHIFT": "Shift",
    "CONTROL": "Ctrl",
    "ALT": "Alt",
    "WIN": "Win",
}


def _mod_sort_key(mod: str) -> int:
    try:
        return MODIFIER_ORDER.index(mod)
    except ValueError:
        return len(MODIFIER_ORDER)


# --------------------------------------------------------------------------
# 归一化
# --------------------------------------------------------------------------

#: 少数平台/版本用的别名键码，统一到标准写法
#:
#: ``left.option`` 归到 ``left.alt``：Minecraft 官方只把 ``left.alt`` 当作内部名，
#: macOS 上显示成 "Left Option" 但内部名不变，所以 ``*.option`` 更可能是 Alt 而非 Win。
_CODE_ALIASES: dict[str, str] = {
    "key.keyboard.left.option": "key.keyboard.left.alt",
    "key.keyboard.right.option": "key.keyboard.right.alt",
    "key.keyboard.left.command": "key.keyboard.left.win",
    "key.keyboard.right.command": "key.keyboard.right.win",
    "key.keyboard.left.meta": "key.keyboard.left.win",
    "key.keyboard.right.meta": "key.keyboard.right.win",
    "key.keyboard.left.super": "key.keyboard.left.win",
    "key.keyboard.right.super": "key.keyboard.right.win",
    "key.keyboard.return": "key.keyboard.enter",
    "key.keyboard.numpad.0": "key.keyboard.keypad.0",
    "key.keyboard.numpad.1": "key.keyboard.keypad.1",
    "key.keyboard.numpad.2": "key.keyboard.keypad.2",
    "key.keyboard.numpad.3": "key.keyboard.keypad.3",
    "key.keyboard.numpad.4": "key.keyboard.keypad.4",
    "key.keyboard.numpad.5": "key.keyboard.keypad.5",
    "key.keyboard.numpad.6": "key.keyboard.keypad.6",
    "key.keyboard.numpad.7": "key.keyboard.keypad.7",
    "key.keyboard.numpad.8": "key.keyboard.keypad.8",
    "key.keyboard.numpad.9": "key.keyboard.keypad.9",
    "key.keyboard.unknown": UNBOUND,
    "key.unknown": UNBOUND,
    "": UNBOUND,
}


def normalise_code(code: str) -> str:
    """把键码归一化成标准命名写法；数字键码会走版本转换表。"""
    code = (code or "").strip()
    if not code:
        return UNBOUND
    if code in _CODE_ALIASES:
        return _CODE_ALIASES[code]

    # 旧版纯数字/LWJGL2 键码
    if code.lstrip("-").isdigit():
        converted = legacy_to_named(int(code))
        return converted or f"key.keyboard.{code}"

    lowered = code.lower()
    if lowered in _CODE_ALIASES:
        return _CODE_ALIASES[lowered]
    return code


# --------------------------------------------------------------------------
# 旧版（1.12.2 及更早）数字键码 <-> 命名键码
# --------------------------------------------------------------------------
# 表在 legacy_codes.py 中，由调研结果生成；此处延迟导入避免循环依赖。

def legacy_to_named(legacy: int) -> str | None:
    from .legacy_codes import LEGACY_TO_NAMED
    return LEGACY_TO_NAMED.get(int(legacy))


def named_to_legacy(code: str) -> int | None:
    from .legacy_codes import NAMED_TO_LEGACY
    return NAMED_TO_LEGACY.get(code)


def detect_code_style(values: Iterable[str]) -> str:
    """猜测一个 options.txt 用的是 ``named`` 还是 ``legacy`` 键码。

    只看已绑定（非 unknown）的值，避免被大量 ``key.keyboard.unknown`` 误导。
    """
    named = 0
    legacy = 0
    for value in values:
        head = (value or "").split(":", 1)[0].strip()
        if not head or head == UNBOUND:
            continue
        if head.lstrip("-").isdigit():
            legacy += 1
        else:
            named += 1
    if legacy > named:
        return "legacy"
    return "named"


#: 合法键值的形状。Minecraft 的 ``InputConstants.getKey()`` 遇到不认识的字符串会
#: 直接抛 ``IllegalArgumentException``，所以写进去之前必须自查。
_VALID_KEY_RE = re.compile(
    r"^key\.(keyboard|mouse|scan)\.[A-Za-z0-9._-]+$"
)


def is_valid_key_code(code: str) -> bool:
    """校验一个键码字符串是否可能被 Minecraft 接受。

    允许：``key.keyboard.*`` / ``key.mouse.*`` / ``key.scan.*``，
    以及 ``key.keyboard.unknown``。数字形式（``key.keyboard.1234``）也合法，
    因为原版会按前缀 + 十进制整数解析。
    """
    if not code:
        return False
    if code == UNBOUND:
        return True
    return bool(_VALID_KEY_RE.match(code))


def is_valid_combo(combo: "KeyCombo") -> bool:
    """校验一个按键组合是否可以被安全写进 options.txt。"""
    if not is_valid_key_code(combo.code):
        return False
    return all(m in MODIFIER_ORDER for m in combo.modifiers)


#: 跨版本改过名字的原版按键：旧名 -> 新名。
#: 同步到新版本实例时要改名，否则写了也会被忽略（该按键在新版本里叫别的名字）。
VANILLA_KEY_RENAMES: dict[str, str] = {
    "key.swapHands": "key.swapOffhand",       # 1.16 起改名
    "key.socialInteractions": "key.otherPlayers",  # 26.4 起改名（前瞻）
}


def renamed_for_version(translation_key: str, mc_version: str | None) -> str:
    """按目标版本把按键的翻译键改成该版本使用的名字。"""
    if not mc_version:
        return translation_key
    parts = _parse_version(mc_version)
    if parts is None:
        return translation_key
    if translation_key == "key.swapHands" and parts >= (1, 16):
        return "key.swapOffhand"
    if translation_key == "key.swapOffhand" and parts < (1, 16):
        return "key.swapHands"
    return translation_key


def _parse_version(text: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d+)\.(\d+)", text.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


# --------------------------------------------------------------------------
# 全部合法命名键码（用于界面下拉框）
# --------------------------------------------------------------------------

def all_named_codes() -> list[str]:
    """返回全部标准命名键码，供 GUI 下拉选择。"""
    codes: list[str] = [UNBOUND]

    # 字母
    codes += [f"key.keyboard.{c}" for c in "abcdefghijklmnopqrstuvwxyz"]
    # 数字
    codes += [f"key.keyboard.{d}" for d in "0123456789"]
    # 功能键
    codes += [f"key.keyboard.f{n}" for n in range(1, 26)]
    # 方向与编辑键
    codes += [
        "key.keyboard.up", "key.keyboard.down",
        "key.keyboard.left", "key.keyboard.right",
        "key.keyboard.space", "key.keyboard.tab", "key.keyboard.enter",
        "key.keyboard.escape", "key.keyboard.backspace",
        "key.keyboard.insert", "key.keyboard.delete",
        "key.keyboard.home", "key.keyboard.end",
        "key.keyboard.page.up", "key.keyboard.page.down",
        "key.keyboard.caps.lock", "key.keyboard.num.lock",
        "key.keyboard.scroll.lock", "key.keyboard.print.screen",
        "key.keyboard.pause", "key.keyboard.menu",
    ]
    # 修饰键
    codes += [
        "key.keyboard.left.shift", "key.keyboard.right.shift",
        "key.keyboard.left.control", "key.keyboard.right.control",
        "key.keyboard.left.alt", "key.keyboard.right.alt",
        "key.keyboard.left.win", "key.keyboard.right.win",
    ]
    # 标点
    codes += [
        "key.keyboard.comma", "key.keyboard.period", "key.keyboard.slash",
        "key.keyboard.semicolon", "key.keyboard.apostrophe",
        "key.keyboard.grave.accent", "key.keyboard.left.bracket",
        "key.keyboard.right.bracket", "key.keyboard.backslash",
        "key.keyboard.minus", "key.keyboard.equal",
    ]
    # 小键盘
    codes += [f"key.keyboard.keypad.{d}" for d in "0123456789"]
    codes += [
        "key.keyboard.keypad.decimal", "key.keyboard.keypad.divide",
        "key.keyboard.keypad.multiply", "key.keyboard.keypad.subtract",
        "key.keyboard.keypad.add", "key.keyboard.keypad.enter",
        "key.keyboard.keypad.equal",
    ]
    # 鼠标
    codes += [
        "key.mouse.left", "key.mouse.right", "key.mouse.middle",
    ] + [f"key.mouse.{n}" for n in range(4, 9)]

    return codes


# --------------------------------------------------------------------------
# 原版按键的翻译键 -> 中文/英文显示名
# --------------------------------------------------------------------------
# Minecraft 自带的按键不在任何 Mod 的语言文件里，必须内置一份。

VANILLA_KEY_NAMES: dict[str, str] = {
    "key.attack": "攻击/破坏",
    "key.use": "使用物品/放置方块",
    "key.forward": "向前",
    "key.left": "向左",
    "key.back": "向后",
    "key.right": "向右",
    "key.jump": "跳跃",
    "key.sneak": "潜行",
    "key.sprint": "疾跑",
    "key.drop": "丢弃物品",
    "key.inventory": "打开/关闭物品栏",
    "key.chat": "打开聊天栏",
    "key.playerlist": "玩家列表",
    "key.pickItem": "选取方块",
    "key.command": "输入命令",
    "key.socialInteractions": "社交屏幕",
    "key.screenshot": "截图",
    "key.togglePerspective": "切换视角",
    "key.smoothCamera": "平滑视角",
    "key.fullscreen": "全屏",
    "key.spectatorOutlines": "高亮玩家（旁观者）",
    "key.swapOffhand": "副手物品交换",
    "key.saveToolbarActivator": "保存物品栏",
    "key.loadToolbarActivator": "加载物品栏",
    "key.advancements": "进度",
    "key.quickActions": "快速操作",
    "key.hotbar.1": "快捷栏 1",
    "key.hotbar.2": "快捷栏 2",
    "key.hotbar.3": "快捷栏 3",
    "key.hotbar.4": "快捷栏 4",
    "key.hotbar.5": "快捷栏 5",
    "key.hotbar.6": "快捷栏 6",
    "key.hotbar.7": "快捷栏 7",
    "key.hotbar.8": "快捷栏 8",
    "key.hotbar.9": "快捷栏 9",
    "key.debug.showHitboxes": "显示碰撞箱",
    "key.debug.reloadChunk": "重载区块",
    "key.debug.clearChat": "清空聊天",
    "key.debug.showDebugInfo": "调试信息",
    "key.debug.showAdvancedTooltips": "高级提示框",
    "key.debug.profiler": "性能分析",
    "key.debug.copyRecreateCommand": "复制重建命令",
    "key.debug.showChunkBorders": "区块边界",
    "key.debug.showChunkId": "区块 ID",
    "key.debug.dumpDynamicTextures": "导出动态贴图",
    "key.debug.cycleRenderDistance": "循环渲染距离",
    "key.debug.spectate": "旁观",
    "key.debug.focusPause": "聚焦暂停",
    "key.debug.pauseFocused": "暂停聚焦",
}

VANILLA_CATEGORY_NAMES: dict[str, str] = {
    "key.categories.movement": "移动",
    "key.categories.gameplay": "游戏玩法",
    "key.categories.inventory": "物品栏",
    "key.categories.creative": "创造模式",
    "key.categories.multiplayer": "多人游戏",
    "key.categories.ui": "界面",
    "key.categories.misc": "杂项",
    "key.categories.debug": "调试",
}
