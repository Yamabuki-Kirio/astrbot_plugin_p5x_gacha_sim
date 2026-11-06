"""数据集加载：把 ``data/items/*.json`` 与 ``data/banners.json`` 读成对象。

插件运行时只读这里产出的不可变对象；管理端要改卡池时改 JSON 再重载即可。
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .models import Banner, Item, PoolError
from .names import CharacterNames, normalize_key

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def excluded_character_ids(base):
    path = base / "excluded_characters.json"
    return set(_load_json(path)) if path.exists() else set()


def _excluded_item(item_id, excluded):
    if item_id in excluded:
        return True
    if item_id.startswith("weapon:"):
        return "char:" + item_id.partition(":")[2].split("-weapon", 1)[0] in excluded
    return False


def load_items(items_dir: Path | None = None) -> dict[str, Item]:
    """读取 items 目录下所有 JSON，按 id 建索引。"""
    items_dir = items_dir or (DATA_DIR / "items")
    items: dict[str, Item] = {}
    for path in sorted(items_dir.glob("*.json")):
        data = _load_json(path)
        entries = data["items"] if isinstance(data, dict) else data
        default_status = data.get("status") if isinstance(data, dict) else None
        for entry in entries:
            if entry.get("rarity") is None:
                continue  # 未上线 / 未定稀有度的角色不进卡池
            entry = dict(entry)
            if default_status and "status" not in entry:
                entry["status"] = default_status
            prefix, _, _rest = str(entry.get("id", "")).partition(":")
            if prefix in {"char", "weapon", "persona"} and not entry.get("kind"):
                entry["kind"] = prefix
            item = Item.from_dict(entry)
            if item.id in items:
                raise PoolError(f"物品 id 重复：{item.id}（{path.name}）")
            items[item.id] = item
    return items


def load_banners(banners_path: Path | None = None, items: dict[str, Item] | None = None) -> list[Banner]:
    banners_path = banners_path or (DATA_DIR / "banners.json")
    items = items if items is not None else load_items()
    entries = deepcopy(_load_json(banners_path))
    excluded = excluded_character_ids(banners_path.parent)
    for entry in entries:
        for field in ("pool", "rate_up"):
            for rarity, item_ids in (entry.get(field) or {}).items():
                entry[field][rarity] = [i for i in item_ids if not _excluded_item(i, excluded)]
    asset_index_path = banners_path.parent / "asset_index.json"
    if asset_index_path.exists():
        drawable = set((_load_json(asset_index_path).get("items") or {}).keys())
        filtered_entries = []
        for original in entries:
            entry = deepcopy(original)
            for field in ("pool", "rate_up"):
                for rarity, item_ids in (entry.get(field) or {}).items():
                    entry[field][rarity] = [
                        item_id
                        for item_id in item_ids
                        if not item_id.startswith(("char:", "weapon:")) or item_id in drawable
                    ]
            filtered_entries.append(entry)
        entries = filtered_entries
    banners = [Banner.from_dict(entry, items) for entry in entries]
    seen: set[str] = set()
    for banner in banners:
        if banner.id in seen:
            raise PoolError(f"卡池 id 重复：{banner.id}")
        seen.add(banner.id)
    return banners


class Registry:
    """物品表 + 卡池表的只读快照。"""

    def __init__(self, items: dict[str, Item], banners: Iterable[Banner], excluded=None):
        self.items = items
        self.excluded = excluded_character_ids(DATA_DIR) if excluded is None else set(excluded)
        self.banners = {banner.id: banner for banner in banners}
        self.names = CharacterNames(items)
        self._build_limited_banners()

    def limited_characters(self):
        return tuple(i for i in self.items.values()
                     if i.id.startswith("char:") and i.rarity == 5 and i.limited and i.id not in self.excluded)

    def limited_weapons(self):
        # 原始武器表只有 owner，限定性由其所属角色的限定性确定。
        owners = {i.id.partition(":")[2] for i in self.limited_characters()}
        return tuple(i for i in self.items.values() if i.id.startswith("weapon:") and i.rarity == 5
                     and i.id.partition(":")[2].split("-weapon", 1)[0] in owners)

    def _build_limited_banners(self):
        for kind, template_id, roster in (
            ("character", "char_limited", self.limited_characters()),
            ("weapon", "weapon_limited", self.limited_weapons()),
        ):
            template = self.banners.get(template_id)
            if template is None or not roster:
                continue
            prefix = "char" if kind == "character" else "weapon"
            pool = dict(template.pool)
            pool[5] = roster
            # 绘图资源不能决定能否抽取。低星仍遵循原池的类别与概率。
            for rarity in (4, 3, 2):
                allowed = {i.kind for i in template.candidates(rarity)}
                pool[rarity] = tuple(i for i in self.items.values() if i.rarity == rarity and i.kind in allowed)
            base = replace(template, id=prefix + "_all_limited", name="全限定角色池" if kind == "character" else "全限定武器池",
                           pool=pool, rate_up={}, selector_at=None, enabled=True,
                           note="五星仅含全部限定角色，等概率抽取" if kind == "character" else "五星仅含限定角色的专武，等概率抽取")
            base.validate()
            self.banners[base.id] = base
            for item in roster:
                targeted = replace(base, id="target:" + item.id, name=item.name + ("·角色池" if kind == "character" else "·武器池"),
                                   rate_up={5: (item,)}, note=f"五星 UP：{item.name}；非 UP 五星仍仅来自限定范围")
                targeted.validate()
                self.banners[targeted.id] = targeted

    def configured_default(self, config):
        kind = config.get("default_pool_type", "character")
        if kind not in ("character", "weapon", "角色", "角色池", "武器池", "武器"):
            raise PoolError(f"无效的默认抽取类型：{kind}")
        weapon = kind in ("weapon", "武器池", "武器")
        target = str(config.get("selected_weapon" if weapon else "selected_character", "") or "").strip()
        if target:
            result = self.resolve_weapon(target) if weapon else self.resolve_character(target)
            if result is None:
                raise PoolError(f"配置的{'武器' if weapon else '角色'}「{target}」不明确或不属于限定范围")
            return result
        legacy = str(config.get("default_banner", "") or "").strip()
        if legacy and legacy != "char_limited":
            found = self.resolve(legacy)
            if found:
                return found
            raise PoolError(f"找不到配置的默认卡池：{legacy}")
        return self.banner("weapon_all_limited" if weapon else "char_all_limited")

    def resolve_character(self, text):
        matches = self.names.search(text)
        if len(matches) == 1:
            return self.banners.get("target:" + matches[0].id)
        return None

    def selection_error(self, text):
        matches = self.names.search(text)
        if len(matches) == 1 and matches[0].id in self.excluded:
            return f"「{matches[0].name}」已暂时下架，等待后续版本更新。"
        if len(matches) > 1:
            return "名称有歧义，请使用完整名称：" + "、".join(i.name for i in matches)
        if len(matches) == 1 and not matches[0].limited:
            return f"「{matches[0].name}」不属于当前限定角色范围。"
        return f"没有找到限定卡池「{text}」。发送 /卡池 查看角色列表。"

    def resolve_weapon(self, text):
        key = normalize_key(text)
        weapons = self.limited_weapons()
        matches = [i for i in weapons if key in (normalize_key(i.id), normalize_key(i.name))]
        if not matches:
            owners = self.names.search(text)
            if len(owners) == 1:
                prefix = "weapon:" + owners[0].id.partition(":")[2] + "-weapon"
                matches = [i for i in weapons if i.id.startswith(prefix)]
        if not matches:
            matches = [i for i in weapons if key and key in normalize_key(i.name)]
        return self.banners.get("target:" + matches[0].id) if len(matches) == 1 else None

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "Registry":
        base = data_dir or DATA_DIR
        items = load_items(base / "items")
        banners = load_banners(base / "banners.json", items)
        registry = cls(items, banners, excluded_character_ids(base))
        registry.names = CharacterNames(items, base / "character_aliases.json")
        return registry

    # ------------------------------------------------------------------
    def enabled_banners(self) -> list[Banner]:
        return [banner for banner in self.banners.values() if banner.enabled]

    def banner(self, banner_id: str) -> Banner:
        try:
            return self.banners[banner_id]
        except KeyError as exc:
            raise KeyError(f"找不到卡池 {banner_id}") from exc

    def resolve(self, text: str) -> Banner | None:
        """支持按 id、完整名、别名和唯一关键字查卡池。"""
        text = (text or "").strip()
        if not text:
            return None
        if text in self.banners:
            return self.banners[text] if self.banners[text].enabled else None
        key = normalize_key(text)
        generic = {"全角色": "char_all_limited", "全角色池": "char_all_limited", "角色池": "char_all_limited",
                   "全限定角色池": "char_all_limited", "全武器": "weapon_all_limited", "全武器池": "weapon_all_limited",
                   "武器池": "weapon_all_limited", "全限定武器池": "weapon_all_limited"}
        if key in generic:
            return self.banners.get(generic[key])
        if text.startswith("武器 ") or text.startswith("武器池 "):
            return self.resolve_weapon(text.split(" ", 1)[1])
        character = self.resolve_character(text)
        if character:
            return character
        # 角色身份已命中但存在歧义或为非限定时，不能绕过身份检索误选其他形态。
        if self.names.search(text):
            return None
        lowered = text.lower()
        for banner in self.banners.values():
            if banner.enabled and banner.name.lower() == lowered:
                return banner
        weapon = self.resolve_weapon(text)
        if weapon:
            return weapon
        hits = [b for b in self.enabled_banners() if lowered in b.name.lower() or lowered in b.id]
        if len(hits) == 1:
            return hits[0]
        return None

    def banners_of_kind(self, kind: str) -> list[Banner]:
        return [b for b in self.enabled_banners() if b.kind == kind]

    def item(self, item_id: str) -> Item | None:
        return self.items.get(item_id)
