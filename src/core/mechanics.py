"""抽卡随机逻辑：基础概率、软保底、硬保底、UP 判定、小保底继承。

核心不变量
----------
1. 每次抽卡先掷一次 ``rng.random()``（0..1），落在 [0, p5) 为 5★，落在
   [p5, p5+p4) 为 4★，其余按 3★:2★ 的权重拆分。这样 5★ 与 4★ 的概率可以
   独立叠加，符合「4★ 及以上」的保底语义。
2. ``pity5`` / ``pity4`` 记录「距离上次该稀有度已经抽了多少发」；抽中即清零。
3. 4★ 硬保底（10 抽）在 5★ 判定之后生效：第 10 抽若没出 5★ 就必出 4★。
4. 小保底：``guaranteed`` 为真则本次 5★/4★ 必定是 UP，否则按 ``up_rate`` 判定；
   歪了就把 ``guaranteed`` 置真，带进下一次（跨卡池继承由 pity_group 保证）。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Sequence

from .collection import owner_id
from .models import Banner, Item, PityState

RARITY_ASC = (2, 3, 4, 5)


@dataclass(frozen=True)
class PullResult:
    """单次抽取的结果，``index`` 是该次在整批中的序号（从 1 开始）。"""

    item: Item
    rarity: int
    is_up: bool
    index: int
    pity5_after: int
    pity4_after: int
    is_new: bool = False

    @property
    def stars(self) -> str:
        from .models import STARS

        return STARS.get(self.rarity, "")


class GachaMechanics:
    """无状态的计算核心；状态通过 ``PityState`` 传入传出。"""

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()

    # ------------------------------------------------------------------
    # 概率
    # ------------------------------------------------------------------
    @staticmethod
    def five_rate(state: PityState, banner: Banner) -> float:
        """第 ``state.pity5 + 1`` 抽出现 5★ 的概率。"""
        count = state.pity5 + 1
        hard = banner.hard_pity.get(5, 80)
        if count >= hard:
            return 1.0
        probability = banner.rates.get(5, 0.008)
        for start, end, increment in sorted(banner.soft_pity):
            if count >= start:
                probability += increment * (min(count, end) - start + 1)
        return min(probability, 1.0)

    @staticmethod
    def hard_pity(banner: Banner, rarity: int) -> int:
        return banner.hard_pity.get(rarity, 10 if rarity == 4 else 80)

    def _roll_low_rarity(self, banner: Banner) -> int:
        """在既没出 5★ 也没出 4★ 的情况下，按剩余权重决定是 3★ 还是 2★。"""
        three = max(banner.rates.get(3, 0.0), 0.0)
        two = max(banner.rates.get(2, 0.0), 0.0)
        if three + two <= 0:
            return 3 if banner.candidates(3) else 2
        if not banner.candidates(3):
            return 2
        if not banner.candidates(2):
            return 3
        return 3 if self.rng.random() < three / (three + two) else 2

    # ------------------------------------------------------------------
    # 抽取
    # ------------------------------------------------------------------
    def _pick_weapon(
        self,
        weapons: Sequence[Item],
        owned_chars: set[str] | None = None,
        owned_copies: dict[str, int] | None = None,
    ) -> Item:
        """武器优先抽取已拥有角色的专武/武器（优先未满阶 6/6）。"""
        if owned_chars:
            matching = [w for w in weapons if owner_id(w) in owned_chars]
            if matching:
                if owned_copies is not None:
                    unmaxed = [w for w in matching if owned_copies.get(w.id, 0) < 7]
                    if unmaxed:
                        return self.rng.choice(unmaxed)
                return self.rng.choice(matching)
        return self.rng.choice(list(weapons))

    def pick_bonus_weapon(
        self,
        banner: Banner,
        owned_chars: set[str] | None = None,
        owned_copies: dict[str, int] | None = None,
    ) -> Item | None:
        """综合池出 5★ 角色时同步抽取一把 5★ 武器（优先已拥有角色且未满阶）。"""
        weapons5 = [i for i in banner.candidates(5) if i.id.startswith("weapon:")]
        chars5 = [i for i in banner.candidates(5) if i.id.startswith("char:")]
        if not weapons5 or not chars5 or banner.ups(5):
            return None
        return self._pick_weapon(weapons5, owned_chars, owned_copies)

    def _choose(
        self,
        banner: Banner,
        rarity: int,
        guaranteed: bool,
        owned_chars: set[str] | None = None,
        owned_copies: dict[str, int] | None = None,
    ) -> tuple[Item, bool, bool]:
        """返回 (物品, 是否 UP, 抽完后 guaranteed 的新值)。"""
        candidates = banner.candidates(rarity)
        ups = banner.ups(rarity)
        if not candidates:
            raise ValueError(f"{banner.name}：{rarity}★ 没有候选物品")

        up_ids = {item.id for item in ups}
        others = [item for item in candidates if item.id not in up_ids]

        # 没有 UP，或没有可歪的对象：只可能出候选池里的东西，视为不重置小保底。
        if not ups or not others:
            pool_items = ups or candidates
            if not ups:
                chars = [i for i in pool_items if i.id.startswith("char:")]
                weapons = [i for i in pool_items if i.id.startswith("weapon:")]
                if chars and weapons:
                    if rarity == 5:
                        # 综合池 5★ 主掉落固定为限定角色，同时由服务层同步附赠一把 5★ 武器（共享出金概率）。
                        return self.rng.choice(chars), False, guaranteed
                    # 4★ 综合池：同时含角色与武器；已有可配对角色时 50/50 平衡，无已有角色时偏向角色。
                    has_owned_weapon = bool(owned_chars and any(owner_id(w) in owned_chars for w in weapons))
                    weapon_prob = 0.50 if (owned_chars is None or has_owned_weapon) else 0.20
                    if self.rng.random() < weapon_prob:
                        item = self._pick_weapon(weapons, owned_chars, owned_copies)
                    else:
                        item = self.rng.choice(chars)
                    return item, False, guaranteed
                if weapons and not chars and owned_chars is not None:
                    item = self._pick_weapon(weapons, owned_chars, owned_copies)
                    return item, False, guaranteed
            item = self.rng.choice(pool_items)
            return item, rarity in (4, 5) and bool(ups), guaranteed if not ups else False

        rate = banner.up_rate.get(rarity, 0.5)
        choose_up = guaranteed or self.rng.random() < rate
        if choose_up:
            return self.rng.choice(list(ups)), True, False
        return self.rng.choice(others), False, True

    def pull(
        self,
        banner: Banner,
        state: PityState,
        index: int = 1,
        owned_chars: set[str] | None = None,
        owned_copies: dict[str, int] | None = None,
    ) -> tuple[PullResult, PityState]:
        if not banner.enabled:
            raise ValueError(f"卡池 {banner.name} 已停用")

        p5 = self.five_rate(state, banner)
        p4 = max(banner.rates.get(4, 0.062), 0.0)
        roll = self.rng.random()

        if roll < p5:
            rarity = 5
        elif state.pity4 + 1 >= self.hard_pity(banner, 4):
            rarity = 4
        elif roll < min(1.0, p5 + p4):
            rarity = 4
        else:
            rarity = self._roll_low_rarity(banner)

        if rarity == 5:
            item, is_up, next_guaranteed5 = self._choose(banner, 5, state.guaranteed5, owned_chars, owned_copies)
            next_guaranteed4 = state.guaranteed4
            pity5, pity4 = 0, 0  # 5★ 同时满足 4★ 保底
        elif rarity == 4:
            item, is_up, next_guaranteed4 = self._choose(banner, 4, state.guaranteed4, owned_chars, owned_copies)
            next_guaranteed5 = state.guaranteed5
            pity5, pity4 = state.pity5 + 1, 0
        else:
            item = self.rng.choice(banner.candidates(rarity))
            is_up = False
            next_guaranteed5 = state.guaranteed5
            next_guaranteed4 = state.guaranteed4
            pity5, pity4 = state.pity5 + 1, state.pity4 + 1

        total = state.total_of(banner.id) + 1
        new_state = replace(
            state,
            pity5=pity5,
            pity4=pity4,
            guaranteed5=next_guaranteed5,
            guaranteed4=next_guaranteed4,
            totals={**dict(state.totals), banner.id: total},
            pulls=state.pulls + 1,
        )
        result = PullResult(
            item=item,
            rarity=rarity,
            is_up=is_up,
            index=index,
            pity5_after=pity5,
            pity4_after=pity4,
        )
        return result, new_state

    def pull_many(
        self,
        banner: Banner,
        state: PityState,
        count: int,
        owned_chars: set[str] | None = None,
        owned_copies: dict[str, int] | None = None,
    ) -> tuple[list[PullResult], PityState]:
        if count <= 0:
            raise ValueError("抽卡次数必须大于 0")
        local_chars = set(owned_chars) if owned_chars is not None else None
        local_copies = dict(owned_copies) if owned_copies is not None else None
        results: list[PullResult] = []
        for index in range(1, count + 1):
            result, state = self.pull(banner, state, index, local_chars, local_copies)
            results.append(result)
            if local_chars is not None and result.item.id.startswith("char:") and result.rarity in (4, 5):
                local_chars.add(result.item.id)
            if local_copies is not None and result.item.id.startswith(("char:", "weapon:")) and result.rarity in (4, 5):
                local_copies[result.item.id] = min(7, local_copies.get(result.item.id, 0) + 1)
        return results, state

    # ------------------------------------------------------------------
    # 展示辅助
    # ------------------------------------------------------------------
    @staticmethod
    def sort_for_display(results: Sequence[PullResult]) -> list[PullResult]:
        """十连展示按稀有度降序、同稀有度保持抽取顺序（记录仍用原始顺序）。"""
        return sorted(results, key=lambda r: -r.rarity)
