"""领域模型：物品（角色 / 武器 / 人格面具）与卡池定义。

这里只放数据结构与校验，不含随机逻辑；随机逻辑见 ``mechanics.py``。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

# 稀有度从高到低，用于排序与展示
RARITIES = (5, 4, 3, 2)
STARS = {5: "★★★★★", 4: "★★★★", 3: "★★★", 2: "★★"}

KIND_LABEL = {
    "character": "角色",
    "weapon": "武器",
    "persona": "人格面具",
}

# id 前缀到物品类别的映射：``personas.json`` / ``weapons.json`` 里没有 ``kind`` 字段，
# 只靠默认值会把人格面具误判成角色，导致渲染时按角色规则放图。
KIND_BY_PREFIX = {
    "char": "character",
    "weapon": "weapon",
    "persona": "persona",
}


def _kind_of(item_id: str, declared: Any = None) -> str:
    if declared:
        return str(declared)
    prefix = item_id.split(":", 1)[0].casefold()
    return KIND_BY_PREFIX.get(prefix, "character")


@dataclass(frozen=True)
class Item:
    """卡池中的一件物品。"""

    id: str
    name: str
    kind: str
    rarity: int
    element: str = ""
    limited: bool = False
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def stars(self) -> str:
        return STARS.get(self.rarity, "")

    @property
    def kind_label(self) -> str:
        return KIND_LABEL.get(self.kind, self.kind)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "rarity": self.rarity,
            "element": self.element,
            "limited": self.limited,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Item":
        item_id = str(data["id"])
        return cls(
            id=item_id,
            name=str(data["name"]),
            kind=_kind_of(item_id, data.get("kind")),
            rarity=int(data["rarity"]),
            element=str(data.get("element", "")),
            limited=bool(data.get("limited", False)),
            meta={k: v for k, v in data.items() if k not in {"id", "name", "kind", "rarity", "element", "limited"}},
        )


@dataclass(frozen=True)
class PityState:
    """某个保底组下的持久化状态。

    ``pity5`` / ``pity4`` 是「距离上次出货已经抽了多少发」，抽中即清零。
    ``guaranteed5`` / ``guaranteed4`` 表示下一次该稀有度是否必定为 UP（小保底歪过）。
    ``totals`` 记录每个卡池的累计抽数，用于常驻池的 300 选自选。
    """

    pity5: int = 0
    pity4: int = 0
    guaranteed5: bool = False
    guaranteed4: bool = False
    totals: Mapping[str, int] = field(default_factory=dict)
    pulls: int = 0

    def to_dict(self) -> dict:
        return {
            "pity5": self.pity5,
            "pity4": self.pity4,
            "guaranteed5": self.guaranteed5,
            "guaranteed4": self.guaranteed4,
            "totals": dict(self.totals),
            "pulls": self.pulls,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "PityState":
        data = data or {}
        return cls(
            pity5=int(data.get("pity5", 0)),
            pity4=int(data.get("pity4", 0)),
            guaranteed5=bool(data.get("guaranteed5", False)),
            guaranteed4=bool(data.get("guaranteed4", False)),
            totals={str(k): int(v) for k, v in (data.get("totals") or {}).items()},
            pulls=int(data.get("pulls", 0)),
        )

    def total_of(self, banner_id: str) -> int:
        return int(self.totals.get(banner_id, 0))

    def with_total(self, banner_id: str, value: int) -> "PityState":
        totals = dict(self.totals)
        totals[banner_id] = value
        return replace(self, totals=totals)


class PoolError(ValueError):
    """卡池配置不合法。"""


@dataclass(frozen=True)
class Banner:
    """一个卡池。

    ``pool`` 与 ``rate_up`` 都以稀有度为键。``rates`` 是「单抽时该稀有度出现的基础
    概率」，5★ + 4★ + 3★ + 2★ 应等于 1（不含保底修正）。
    """

    id: str
    name: str
    kind: str  # character / weapon
    pity_group: str
    cost: int
    pool: Mapping[int, tuple[Item, ...]]
    rate_up: Mapping[int, tuple[Item, ...]]
    rates: Mapping[int, float]
    up_rate: Mapping[int, float]
    hard_pity: Mapping[int, int]
    soft_pity: tuple[tuple[int, int, float], ...] = ()
    selector_at: int | None = None
    note: str = ""
    enabled: bool = True

    @property
    def kind_label(self) -> str:
        return KIND_LABEL.get(self.kind, self.kind)

    # ------------------------------------------------------------------
    # 构造与校验
    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Mapping[str, Any], items: Mapping[str, Item]) -> "Banner":
        pool: dict[int, tuple[Item, ...]] = {}
        for rarity_key, ids in (data.get("pool") or {}).items():
            rarity = int(rarity_key)
            resolved = []
            for item_id in ids:
                item = items.get(item_id)
                if item is None:
                    raise PoolError(f"卡池 {data.get('id')} 引用了不存在的物品 {item_id}")
                resolved.append(item)
            pool[rarity] = tuple(resolved)

        rate_up: dict[int, tuple[Item, ...]] = {}
        for rarity_key, ids in (data.get("rate_up") or {}).items():
            rarity = int(rarity_key)
            resolved = []
            for item_id in ids:
                item = items.get(item_id)
                if item is None:
                    raise PoolError(f"卡池 {data.get('id')} 的 UP 引用了不存在的物品 {item_id}")
                resolved.append(item)
            rate_up[rarity] = tuple(resolved)

        rates = {int(k): float(v) for k, v in (data.get("rates") or {}).items()}
        up_rate = {int(k): float(v) for k, v in (data.get("up_rate") or {}).items()}
        hard_pity = {int(k): int(v) for k, v in (data.get("hard_pity") or {}).items()}
        soft = tuple(
            (int(part["start"]), int(part["end"]), float(part["increment"]))
            for part in (data.get("soft_pity") or [])
        )

        banner = cls(
            id=str(data["id"]),
            name=str(data["name"]),
            kind=str(data.get("kind", "character")),
            pity_group=str(data.get("pity_group") or data["id"]),
            cost=int(data.get("cost", 0)),
            pool=pool,
            rate_up=rate_up,
            rates=rates,
            up_rate=up_rate,
            hard_pity=hard_pity,
            soft_pity=soft,
            selector_at=data.get("selector_at"),
            note=str(data.get("note", "")),
            enabled=bool(data.get("enabled", True)),
        )
        banner.validate()
        return banner

    def validate(self) -> None:
        for rarity in (5, 4):
            if not self.pool.get(rarity):
                raise PoolError(f"{self.name}：缺少 {rarity}★ 候选")
        low = self.pool.get(3) or self.pool.get(2)
        if not low:
            raise PoolError(f"{self.name}：缺少 2★/3★ 候选")
        if 5 not in self.hard_pity:
            raise PoolError(f"{self.name}：缺少 5★ 硬保底")
        total = sum(self.rates.get(r, 0.0) for r in RARITIES)
        if abs(total - 1.0) > 1e-6:
            raise PoolError(f"{self.name}：概率之和为 {total:.4f}，应为 1")
        for rarity, ups in self.rate_up.items():
            unknown = {item.id for item in ups} - {item.id for item in self.pool.get(rarity, ())}
            if unknown:
                raise PoolError(f"{self.name}：{rarity}★ 的 UP 不在候选池内：{sorted(unknown)}")
            if ups and not 0 <= self.up_rate.get(rarity, 0.0) <= 1:
                raise PoolError(f"{self.name}：{rarity}★ UP 概率必须在 0..1")

    # ------------------------------------------------------------------
    # 查询辅助
    # ------------------------------------------------------------------
    def candidates(self, rarity: int) -> tuple[Item, ...]:
        return self.pool.get(rarity, ())

    def ups(self, rarity: int) -> tuple[Item, ...]:
        return self.rate_up.get(rarity, ())

    def has_off_rate(self, rarity: int) -> bool:
        """该稀有度是否存在「歪」的可能（有 UP 也有非 UP）。"""
        ups = {item.id for item in self.ups(rarity)}
        return bool(ups) and any(item.id not in ups for item in self.candidates(rarity))

    def max_pity_hint(self) -> int:
        """最坏情况下拿到 UP 需要多少抽（角色 80、武器 140）。"""
        hard5 = self.hard_pity.get(5, 80)
        return hard5 * 2 if self.has_off_rate(5) else hard5

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "pity_group": self.pity_group,
            "cost": self.cost,
            "rates": self.rates,
            "up_rate": self.up_rate,
            "hard_pity": self.hard_pity,
            "soft_pity": [{"start": s, "end": e, "increment": i} for s, e, i in self.soft_pity],
            "selector_at": self.selector_at,
            "note": self.note,
            "enabled": self.enabled,
            "pool": {str(r): [item.id for item in items] for r, items in self.pool.items()},
            "rate_up": {str(r): [item.id for item in items] for r, items in self.rate_up.items()},
        }


def iter_items(banner: Banner) -> Iterable[Item]:
    seen: set[str] = set()
    for items in banner.pool.values():
        for item in items:
            if item.id not in seen:
                seen.add(item.id)
                yield item
