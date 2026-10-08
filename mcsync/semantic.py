# -*- coding: utf-8 -*-
"""同功能按键的跨 Mod 语义映射。

解决这样一类问题：整合包 A 装的是 Xaero 小地图，整合包 B 装的是 JourneyMap，
两者的「打开世界地图」是**不同的绑定名**，靠名字精确匹配对不上。

为此维护一张「语义动作 -> 候选翻译键」的表。用户也可以在
``<数据目录>/semantic_overrides.json`` 里追加自己的映射，格式::

    {
      "open_world_map": ["key.journeymap.fullscreen", "modid:bindingsuffix"]
    }

参考：``Just Universal Keybinds`` 的 "Smart mod keybind grouping" 是目前唯一
做了这件事的现成方案，但闭源且必须每个整合包都装。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

#: 语义动作 -> 候选翻译键（options.txt 里去掉 ``key_`` 前缀后的那串）
#: 只收录**已核实**的映射；不确定的一律不写，宁缺毋滥。
SEMANTIC_ACTIONS: dict[str, tuple[str, ...]] = {
    # ---- 小地图 / 世界地图 -------------------------------------------------
    "open_world_map": (
        "gui.xaero_open_map",              # Xaero's World Map
        "key.journeymap.fullscreen",       # JourneyMap 全屏地图
        "key.journeymap.openMap",
    ),
    "toggle_minimap": (
        "gui.xaero_toggle_map",            # Xaero's Minimap
        "key.journeymap.minimap",
        "key.journeymap.toggleMiniMap",
    ),
    "minimap_settings": (
        "gui.xaero_minimap_settings",
        "gui.xaero_open_settings",
        "key.journeymap.settings",
    ),
    "minimap_zoom_in": (
        "gui.xaero_zoom_in",
        "gui.xaero_map_zoom_in",
        "key.journeymap.zoomIn",
    ),
    "minimap_zoom_out": (
        "gui.xaero_zoom_out",
        "gui.xaero_map_zoom_out",
        "key.journeymap.zoomOut",
    ),
    "waypoint_create": (
        "gui.xaero_new_waypoint",
        "key.journeymap.createWaypoint",
    ),
    "waypoint_list": (
        "gui.xaero_waypoints_key",
        "key.journeymap.waypointManager",
    ),
    "waypoint_quick": (
        "gui.xaero_instant_waypoint",
        "key.journeymap.instantWaypoint",
    ),

    # ---- 合成表 / 物品信息（JEI / REI / EMI） ------------------------------
    "recipe_show": (
        "key.jei.showRecipe",
        "key.rei.showRecipe",
        "key.emi.view_recipes",
        "key.emi.show_recipe",
    ),
    "recipe_uses": (
        "key.jei.showUses",
        "key.rei.showUses",
        "key.emi.view_uses",
        "key.emi.show_uses",
    ),
    "recipe_toggle_overlay": (
        "key.jei.toggleOverlay",
        "key.rei.toggleOverlay",
        "key.emi.toggle_overlay",
    ),
    "recipe_focus_search": (
        "key.jei.focusSearch",
        "key.rei.focusSearch",
        "key.emi.focus_search",
    ),
    "recipe_next_page": ("key.jei.nextPage", "key.rei.nextPage"),
    "recipe_previous_page": ("key.jei.previousPage", "key.rei.previousPage"),

    # ---- 背包 / 饰品栏 -----------------------------------------------------
    "open_backpack": (
        "key.sophisticatedbackpacks.open_backpack",
        "hotKey.fxntstorage.toggle_backpack",
        "key.travelersbackpack.open_backpack",
        "key.inventorysorter.open_backpack",
    ),
    "open_curios": ("key.curios.open.desc", "key.trinkets.open"),

    # ---- 进度 / 任务 / 模组菜单 --------------------------------------------
    "open_advancements": ("key.advancements", "key.ftbquests.quests"),
    "open_mod_list": ("key.configured.open_mod_list",),

    # ---- 通用 zoom ---------------------------------------------------------
    "zoom": (
        "key.chloride.zoom",
        "key.ok_zoomer.zoom",
        "key.zoomify.zoom",
        "key.zoomer.zoom",
        "key.zoom.zoom",
    ),

    # ---- 原版常用项（保证「原版功能」永远在同一组里） -----------------------
    "sprint": ("key.sprint",),
    "sneak": ("key.sneak",),
    "inventory": ("key.inventory",),
    "jump": ("key.jump",),
    "drop": ("key.drop",),
    "chat": ("key.chat",),
    "perspective": ("key.togglePerspective",),
    "screenshot": ("key.screenshot",),
}

#: 反向索引：翻译键 -> 语义动作
_TRANSLATION_TO_ACTION: dict[str, str] = {}
for _action, _keys in SEMANTIC_ACTIONS.items():
    for _k in _keys:
        _TRANSLATION_TO_ACTION.setdefault(_k, _action)


@dataclass
class SemanticGrouper:
    """把绑定名归入语义动作，用于跨 Mod 对齐。"""

    actions: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(SEMANTIC_ACTIONS))

    @classmethod
    def load(cls, overrides_path: Path | None = None) -> "SemanticGrouper":
        actions = {k: tuple(v) for k, v in SEMANTIC_ACTIONS.items()}
        if overrides_path is not None and overrides_path.is_file():
            try:
                extra = json.loads(overrides_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                extra = {}
            if isinstance(extra, dict):
                for action, keys in extra.items():
                    if not isinstance(action, str) or not isinstance(keys, list):
                        continue
                    merged = list(actions.get(action, ()))
                    for k in keys:
                        if isinstance(k, str) and k not in merged:
                            merged.append(k)
                    actions[action] = tuple(merged)
        return cls(actions=actions)

    def save_overrides(self, path: Path) -> None:
        """只写出与内置表不同的部分。"""
        diff = {
            action: [k for k in keys if k not in SEMANTIC_ACTIONS.get(action, ())]
            for action, keys in self.actions.items()
        }
        diff = {a: ks for a, ks in diff.items() if ks}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- 查询 ------------------------------------------------------------
    def action_of(self, translation_key: str) -> str | None:
        """翻译键属于哪个语义动作。"""
        if translation_key in _TRANSLATION_TO_ACTION:
            return _TRANSLATION_TO_ACTION[translation_key]
        for action, keys in self.actions.items():
            if translation_key in keys:
                return action
        return None

    def candidates(self, action: str) -> tuple[str, ...]:
        return self.actions.get(action, ())

    def peers(self, translation_key: str) -> list[str]:
        """同一语义动作下、**其它** mod 的等价翻译键。"""
        action = self.action_of(translation_key)
        if action is None:
            return []
        return [k for k in self.candidates(action) if k != translation_key]

    def link(self, action: str, translation_key: str) -> None:
        """把一个翻译键登记到某个语义动作（用户手动关联时用）。"""
        keys = list(self.actions.get(action, ()))
        if translation_key not in keys:
            keys.append(translation_key)
        self.actions[action] = tuple(keys)
        _TRANSLATION_TO_ACTION.setdefault(translation_key, action)


# --------------------------------------------------------------------------
# Mod 家族：把同一个 mod 的多个按键归到一起（比如 Xaero 小地图 vs 世界地图）
# --------------------------------------------------------------------------

#: modid -> 家族名。同家族的按键在界面上合并显示，也方便整组同步。
MOD_FAMILIES: dict[str, str] = {
    "xaerominimap": "Xaero 地图",
    "xaeroworldmap": "Xaero 地图",
    "xaerobetterpvp": "Xaero 地图",
    "journeymap": "JourneyMap",
    "jei": "JEI",
    "roughlyenoughitems": "REI",
    "emi": "EMI",
    "sophisticatedbackpacks": "Sophisticated Backpacks",
    "travelersbackpack": "Traveler's Backpack",
    "curios": "Curios",
    "trinkets": "Trinkets",
    "create": "Create",
    "ponder": "Create",
    "flywheel": "Create",
}


def family_of(mod_id: str | None) -> str | None:
    """按 modid 查家族名。"""
    if not mod_id:
        return None
    return MOD_FAMILIES.get(mod_id.lower())


#: 出现在按键名里但没有信息量的片段，用于美化显示名时剔除
NOISE_TOKENS: frozenset[str] = frozenset({
    "key", "keys", "keyinfo", "info", "desc", "description", "keybind",
    "keybindings", "category", "categories", "gui", "hotkey", "hotkeys",
    "binding", "bindings", "action", "actions",
})


def family_from_key(translation_key: str) -> str | None:
    """从翻译键本身推断 mod 家族。

    有些 Mod 的翻译键前缀和 modid 对不上（例如 ``key_gui.xaero_pac_key_open_menu``
    来自 ``openpartiesandclaims``），或者语言文件缺失导致无法归属。
    此时用名字片段去匹配已知家族成员，**只在唯一命中时**返回。
    """
    tokens = [t for t in _SPLIT_RE.split(translation_key.lower())
              if len(t) >= 4 and t not in NOISE_TOKENS]
    if not tokens:
        return None

    families: set[str] = set()
    for token in tokens:
        for mod_id, family in MOD_FAMILIES.items():
            normalised = mod_id.replace("_", "").replace("-", "")
            if token in normalised or normalised.startswith(token):
                families.add(family)
                break
    if len(families) == 1:
        return next(iter(families))
    return None


_SPLIT_RE = re.compile(r"[._\-/]+")
