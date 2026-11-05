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
    def _choose(self, banner: Banner, rarity: int, guaranteed: bool) -> tuple[Item, bool, bool]:
        """返回 (物品, 是否 UP, 抽完后 guaranteed 的新值)。"""
        candidates = banner.candidates(rarity)
        ups = banner.ups(rarity)
        if not candidates:
            raise ValueError(f"{banner.name}：{rarity}★ 没有候选物品")

        up_ids = {item.id for item in ups}
        others = [item for item in candidates if item.id not in up_ids]

        # 没有 UP，或没有可歪的对象：只可能出候选池里的东西，视为不重置小保底。
        if not ups or not others:
            item = self.rng.choice(ups or candidates)
            return item, rarity in (4, 5) and bool(ups), False

        rate = banner.up_rate.get(rarity, 0.5)
        choose_up = guaranteed or self.rng.random() < rate
        if choose_up:
            return self.rng.choice(list(ups)), True, False
        return self.rng.choice(others), False, True

    def pull(self, banner: Banner, state: PityState, index: int = 1) -> tuple[PullResult, PityState]:
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
            item, is_up, next_guaranteed5 = self._choose(banner, 5, state.guaranteed5)
            next_guaranteed4 = state.guaranteed4
            pity5, pity4 = 0, 0  # 5★ 同时满足 4★ 保底
        elif rarity == 4:
            item, is_up, next_guaranteed4 = self._choose(banner, 4, state.guaranteed4)
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

    def pull_many(self, banner: Banner, state: PityState, count: int) -> tuple[list[PullResult], PityState]:
        if count <= 0:
            raise ValueError("抽卡次数必须大于 0")
        results: list[PullResult] = []
        for index in range(1, count + 1):
            result, state = self.pull(banner, state, index)
            results.append(result)
        return results, state

    # ------------------------------------------------------------------
    # 展示辅助
    # ------------------------------------------------------------------
    @staticmethod
    def sort_for_display(results: Sequence[PullResult]) -> list[PullResult]:
        """十连展示按稀有度降序、同稀有度保持抽取顺序（记录仍用原始顺序）。"""
        return sorted(results, key=lambda r: -r.rarity)
