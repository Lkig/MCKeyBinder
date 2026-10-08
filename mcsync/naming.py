# -*- coding: utf-8 -*-
"""按键命名解析：把 options.txt 里的一串天书变成人能看懂的条目。

优先级（高 -> 低）：

1. **原版内置表** —— ``key.sneak`` -> 「潜行」。原版按键不在任何 mod 的语言文件里。
2. **mod 语言文件** —— ``key.jei.showRecipe`` -> 「显示配方」；``gui.xaero_open_map``
   -> 「打开世界地图」。实测这是覆盖最广、最准的来源。
3. **打分猜归属** —— 语言文件缺失时，用名字片段匹配已安装的 modid。
4. **人肉美化** —— 都没有就退化成 ``mod 名 · 去掉下划线的动作``，至少比原始字符串好读。

分组（界面里的「分类」列）：
  * 原版按键按 Minecraft 自带的分类（移动 / 游戏玩法 / 物品栏 / …）。
  * mod 按键按其归属 mod 分组。

注意：``options.txt`` **不存分类信息**，分类是 KeyMapping 注册时确定的。
所以 mod 按键的分类只能靠语言文件 + 归属推断，拿不到时归到「未分类」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .keycodes import VANILLA_CATEGORY_NAMES, VANILLA_KEY_NAMES
from .modscan import ModIndex
from .semantic import NOISE_TOKENS, SemanticGrouper, family_from_key, family_of

#: 原版按键的翻译键 -> 分类翻译键（Minecraft 源码里的注册分类）
VANILLA_KEY_CATEGORY: dict[str, str] = {
    "key.attack": "key.categories.gameplay",
    "key.use": "key.categories.gameplay",
    "key.pickItem": "key.categories.gameplay",
    "key.drop": "key.categories.gameplay",
    "key.hotbar.1": "key.categories.inventory",
    "key.hotbar.2": "key.categories.inventory",
    "key.hotbar.3": "key.categories.inventory",
    "key.hotbar.4": "key.categories.inventory",
    "key.hotbar.5": "key.categories.inventory",
    "key.hotbar.6": "key.categories.inventory",
    "key.hotbar.7": "key.categories.inventory",
    "key.hotbar.8": "key.categories.inventory",
    "key.hotbar.9": "key.categories.inventory",
    "key.inventory": "key.categories.inventory",
    "key.swapOffhand": "key.categories.inventory",
    "key.saveToolbarActivator": "key.categories.creative",
    "key.loadToolbarActivator": "key.categories.creative",
    "key.forward": "key.categories.movement",
    "key.left": "key.categories.movement",
    "key.back": "key.categories.movement",
    "key.right": "key.categories.movement",
    "key.jump": "key.categories.movement",
    "key.sneak": "key.categories.movement",
    "key.sprint": "key.categories.movement",
    "key.chat": "key.categories.multiplayer",
    "key.playerlist": "key.categories.multiplayer",
    "key.command": "key.categories.multiplayer",
    "key.socialInteractions": "key.categories.multiplayer",
    "key.advancements": "key.categories.misc",
    "key.screenshot": "key.categories.misc",
    "key.togglePerspective": "key.categories.misc",
    "key.smoothCamera": "key.categories.misc",
    "key.fullscreen": "key.categories.misc",
    "key.spectatorOutlines": "key.categories.misc",
}

_WORD_SPLIT_RE = re.compile(r"[._\-/]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def prettify_suffix(translation_key: str, owner_mod: str | None = None) -> str:
    """把 ``irons_spellbooks.spell_wheel`` 这种变成 ``Spell wheel``。

    不追求完美翻译，只求比原始字符串好读。三步：

    1. 去掉**开头**属于 modid 的部分（按 modid 自己的分词比对）。
       不能简单地「整段是 modid 的子串就删」——``spell`` 也是
       ``irons_spellbooks`` 的子串，那样会把有意义的部分也删掉。
    2. 去掉 ``keyinfo`` / ``desc`` / ``gui`` 这类没有信息量的片段，但至少留一段。
    3. 首字母大写。
    """
    parts = [p for p in _WORD_SPLIT_RE.split(translation_key) if p]
    if not parts:
        return translation_key

    owner_tokens = {t for t in _WORD_SPLIT_RE.split((owner_mod or "").lower()) if t}
    owner_norm = re.sub(r"[^a-z0-9]", "", (owner_mod or "").lower())

    if owner_tokens:
        while parts:
            head = re.sub(r"[^a-z0-9]", "", parts[0].lower())
            if head in owner_tokens or (len(head) >= 3 and head == owner_norm):
                parts.pop(0)
            else:
                break
    elif len(parts) > 1:
        parts = parts[1:]   # 归属未知时，只丢掉最可能是 mod 名的那一段

    cleaned = [p for p in parts if p.lower() not in NOISE_TOKENS]
    if cleaned:
        parts = cleaned
    elif owner_mod:
        parts = [owner_mod]      # 全被噪声词吃掉了，退回到 mod 名
    elif parts:
        parts = parts[-1:]

    text = " ".join(_CAMEL_RE.sub(" ", p) for p in parts).strip()
    if not text:
        return translation_key
    # 首字母大写，看起来更像一个按键名而不是代码片段
    return text[0].upper() + text[1:]


@dataclass
class BindingInfo:
    """一个按键绑定在界面里需要的全部展示信息。"""

    binding_name: str        # key_key.jei.showRecipe
    translation_key: str     # key.jei.showRecipe
    display: str             # 显示配方
    owner_mod: str | None    # jei
    owner_name: str          # JEI
    group: str               # 分组名
    is_vanilla: bool
    semantic_action: str | None

    @property
    def search_text(self) -> str:
        return " ".join(filter(None, (
            self.binding_name, self.translation_key, self.display,
            self.owner_mod, self.owner_name, self.group,
        ))).lower()


class NamingResolver:
    """把绑定名解析成 :class:`BindingInfo`，并缓存结果。"""

    def __init__(self, index: ModIndex,
                 semantic: SemanticGrouper | None = None) -> None:
        self.index = index
        self.semantic = semantic or SemanticGrouper.load()
        self._cache: dict[tuple[str, str], BindingInfo] = {}

    # -- 主入口 ----------------------------------------------------------
    def resolve(self, binding_name: str, instance_key: str = "") -> BindingInfo:
        cache_key = (binding_name, instance_key)
        hit = self._cache.get(cache_key)
        if hit is not None:
            return hit
        info = self._resolve_uncached(binding_name, instance_key)
        self._cache[cache_key] = info
        return info

    def _resolve_uncached(self, binding_name: str, instance_key: str) -> BindingInfo:
        translation_key = binding_name[4:] if binding_name.startswith("key_") \
            else binding_name

        # 1) 原版
        if translation_key in VANILLA_KEY_NAMES:
            cat_key = VANILLA_KEY_CATEGORY.get(translation_key, "key.categories.misc")
            return BindingInfo(
                binding_name=binding_name,
                translation_key=translation_key,
                display=VANILLA_KEY_NAMES[translation_key],
                owner_mod="minecraft",
                owner_name="Minecraft 原版",
                group=VANILLA_CATEGORY_NAMES.get(cat_key, "原版"),
                is_vanilla=True,
                semantic_action=self.semantic.action_of(translation_key),
            )

        # 2) mod 语言文件
        display = self.index.display_name(translation_key)
        owner = self.index.owner_mod(translation_key)

        # 3) 打分猜归属
        if owner is None:
            pool = self.index.instance_mod_ids(instance_key) or None
            owner = self.index.guess_owner(translation_key, pool)

        owner_name = ""
        if owner:
            mod = self.index.mods.get(owner)
            owner_name = (mod.label if mod else owner)

        if not display:
            # 4) 人肉美化
            pretty = prettify_suffix(translation_key, owner)
            display = pretty or owner_name or translation_key

        group = self._group_for(owner, owner_name, translation_key)
        return BindingInfo(
            binding_name=binding_name,
            translation_key=translation_key,
            display=display,
            owner_mod=owner,
            owner_name=owner_name,
            group=group,
            is_vanilla=False,
            semantic_action=self.semantic.action_of(translation_key),
        )

    @staticmethod
    def _group_for(owner: str | None, owner_name: str,
                   translation_key: str) -> str:
        family = family_of(owner)
        if family:
            return family
        if owner_name:
            return owner_name
        # 语言文件缺失、归属也猜不出来时，用名字片段去匹配已知 mod 家族
        # （例如 key_gui.xaero_pac_key_open_menu 其实来自开团与区块声索）
        family = family_from_key(translation_key)
        if family:
            return family
        # 最后用翻译键的第一段当兜底分组名
        head = _WORD_SPLIT_RE.split(translation_key)
        head = [p for p in head if p.lower() not in NOISE_TOKENS]
        return head[0] if head else "未分类"

    # -- 便捷查询 --------------------------------------------------------
    def display(self, binding_name: str, instance_key: str = "") -> str:
        return self.resolve(binding_name, instance_key).display

    def sort_key(self, binding_name: str, instance_key: str = "") -> tuple:
        info = self.resolve(binding_name, instance_key)
        return (0 if info.is_vanilla else 1, info.group.lower(),
                info.owner_name.lower(), info.display.lower())
