"""数据集加载：把 ``data/items/*.json`` 与 ``data/banners.json`` 读成对象。

插件运行时只读这里产出的不可变对象；管理端要改卡池时改 JSON 再重载即可。
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Iterable

from .models import Banner, Item, PoolError

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


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
    entries = _load_json(banners_path)
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

    def __init__(self, items: dict[str, Item], banners: Iterable[Banner]):
        self.items = items
        self.banners = {banner.id: banner for banner in banners}

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "Registry":
        base = data_dir or DATA_DIR
        items = load_items(base / "items")
        banners = load_banners(base / "banners.json", items)
        return cls(items, banners)

    # ------------------------------------------------------------------
    def enabled_banners(self) -> list[Banner]:
        return [banner for banner in self.banners.values() if banner.enabled]

    def banner(self, banner_id: str) -> Banner:
        try:
            return self.banners[banner_id]
        except KeyError as exc:
            raise KeyError(f"找不到卡池 {banner_id}") from exc

    def resolve(self, text: str) -> Banner | None:
        """支持按 id、完整名、关键字（唯一匹配）或 ``#序号`` 查卡池。"""
        text = (text or "").strip()
        if not text:
            return None
        if text in self.banners:
            return self.banners[text]
        lowered = text.lower()
        for banner in self.banners.values():
            if banner.name.lower() == lowered:
                return banner
        hits = [b for b in self.banners.values() if lowered in b.name.lower() or lowered in b.id]
        if len(hits) == 1:
            return hits[0]
        return None

    def banners_of_kind(self, kind: str) -> list[Banner]:
        return [b for b in self.enabled_banners() if b.kind == kind]

    def item(self, item_id: str) -> Item | None:
        return self.items.get(item_id)
