"""抽卡服务：把「读状态 → 抽 → 写状态 + 历史」包成一个原子操作，并负责文案。

AstrBot 侧只调用这里的函数，不直接碰数据库和随机数。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from ..core.mechanics import GachaMechanics, PullResult
from ..core.models import Banner, PityState
from ..core.registry import Registry
from ..core.store import Store


@dataclass
class DrawOutcome:
    banner: Banner
    results: list[PullResult]
    state: PityState
    cost: int
    elapsed_ms: int

    @property
    def five_stars(self) -> list[PullResult]:
        return [r for r in self.results if r.rarity == 5]

    @property
    def four_stars(self) -> list[PullResult]:
        return [r for r in self.results if r.rarity == 4]


class GachaService:
    def __init__(self, registry: Registry, store: Store, record_history: bool = True):
        self.registry = registry
        self.store = store
        self.record_history = record_history
        self.mechanics = GachaMechanics()
        # 抽卡是「读改写」，串行化避免同一用户并发抽卡时保底计数丢失
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def draw(self, platform_id: str, user_id: str, banner: Banner, count: int) -> DrawOutcome:
        if count not in (1, 10):
            raise ValueError("只支持单抽或十连")
        if not banner.enabled:
            raise ValueError(f"卡池「{banner.name}」已停用")
        started = time.perf_counter()
        with self._lock:
            state = self.store.load_state(platform_id, user_id, banner.pity_group)
            results, new_state = self.mechanics.pull_many(banner, state, count)
            self.store.save_state(platform_id, user_id, banner.pity_group, new_state)
            if self.record_history:
                self.store.add_history(
                    platform_id,
                    user_id,
                    banner.id,
                    [(r.item.id, r.item.name, r.rarity, r.is_up) for r in results],
                )
        return DrawOutcome(
            banner=banner,
            results=results,
            state=new_state,
            cost=banner.cost * count,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    # ------------------------------------------------------------------
    def state_of(self, platform_id: str, user_id: str, banner: Banner) -> PityState:
        return self.store.load_state(platform_id, user_id, banner.pity_group)

    def select_character(self, platform_id: str, user_id: str, banner: Banner, item_id: str) -> str:
        """常驻池 300 抽自选：满足抽数就发一个 5★ 并把计数清零。"""
        if not banner.selector_at:
            raise ValueError("该卡池没有自选机制")
        state = self.state_of(platform_id, user_id, banner)
        total = state.total_of(banner.id)
        if total < banner.selector_at:
            raise ValueError(f"还没有到 {banner.selector_at} 抽（当前 {total} 抽）")
        item = self.registry.item(item_id)
        if item is None or item.rarity != 5 or item not in banner.candidates(5):
            raise ValueError("只能从本卡池的 5★ 候选里选")
        if self.record_history:
            self.store.add_history(platform_id, user_id, banner.id, [(item.id, item.name, 5, False)])
        self.store.save_state(
            platform_id, user_id, banner.pity_group, state.with_total(banner.id, total - banner.selector_at)
        )
        return item.name

    # ------------------------------------------------------------------
    # 文案
    # ------------------------------------------------------------------
    @staticmethod
    def format_result_line(result: PullResult) -> str:
        parts = [result.item.stars, result.item.name]
        if result.item.element:
            parts.append(f"（{result.item.element}）")
        if result.is_up:
            parts.append(" · UP")
        return "".join(parts)

    def format_ten(self, outcome: DrawOutcome) -> str:
        lines = [f"【{outcome.banner.name}】十连结果"]
        for index, result in enumerate(outcome.results, 1):
            lines.append(f"{index:>2}. {self.format_result_line(result)}")
        lines.append(
            f"—— 5★ ×{len(outcome.five_stars)} · 4★ ×{len(outcome.four_stars)} · 消耗 {outcome.cost} 晶珀"
        )
        lines.append(self.format_pity_short(outcome.banner, outcome.state))
        return "\n".join(lines)

    def format_single(self, outcome: DrawOutcome) -> str:
        result = outcome.results[0]
        return "\n".join(
            [
                f"【{outcome.banner.name}】单抽结果",
                self.format_result_line(result),
                f"—— 消耗 {outcome.cost} 晶珀",
                self.format_pity_short(outcome.banner, outcome.state),
            ]
        )

    @staticmethod
    def format_pity_short(banner: Banner, state: PityState) -> str:
        hard5 = banner.hard_pity.get(5, 80)
        hard4 = banner.hard_pity.get(4, 10)
        text = f"5★ 保底 {state.pity5}/{hard5}（还差 {hard5 - state.pity5} 抽） · 4★ {state.pity4}/{hard4}"
        if banner.has_off_rate(5):
            text += " · 大保底：" + ("已触发，下次 5★ 必为 UP" if state.guaranteed5 else "未触发")
        return text

    def format_pity(self, banner: Banner, state: PityState) -> str:
        hard5 = banner.hard_pity.get(5, 80)
        hard4 = banner.hard_pity.get(4, 10)
        lines = [
            f"【{banner.name}】保底状态",
            f"5★ 已垫 {state.pity5}/{hard5} 抽，最多再 {hard5 - state.pity5} 抽必出",
            f"4★ 已垫 {state.pity4}/{hard4} 抽，最多再 {hard4 - state.pity4} 抽必出 4★ 及以上",
        ]
        if banner.has_off_rate(5):
            rate = banner.up_rate.get(5, 0.5)
            if state.guaranteed5:
                lines.append("大保底：已触发，下一次 5★ 必定是当期 UP")
            else:
                lines.append(f"小保底：未触发，下一次 5★ 有 {rate:.0%} 概率是 UP，否则进入大保底")
            lines.append(f"最坏情况：{banner.max_pity_hint()} 抽必得 UP")
        else:
            lines.append("本卡池没有 UP，5★ 等概率随机")
        lines.append(f"本池累计 {state.total_of(banner.id)} 抽（跨期继承：{banner.pity_group}）")
        if banner.selector_at:
            total = state.total_of(banner.id)
            lines.append(f"常驻自选：{banner.selector_at} 抽可选一个 5★，当前 {total} 抽")
        return "\n".join(lines)

    def format_history(self, platform_id: str, user_id: str, banner: Banner | None, page: int, page_size: int = 10) -> str:
        banner_id = banner.id if banner else None
        total = self.store.count_history(platform_id, user_id, banner_id)
        if total == 0:
            return "还没有抽卡记录。"
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(max(1, page), pages)
        rows = self.store.history(platform_id, user_id, page_size, (page - 1) * page_size, banner_id)
        lines = [f"抽卡记录（{page}/{pages} 页，共 {total} 条）"]
        for row in rows:
            stamp = time.strftime("%m-%d %H:%M", time.localtime(row["created_at"]))
            stars = "★" * row["rarity"]
            up = " UP" if row["is_up"] else ""
            lines.append(f"{stamp}  {stars} {row['item_name']}{up}")
        summary = self.store.rarity_summary(platform_id, user_id, banner_id)
        if summary:
            detail = " · ".join(f"{r}★×{n}" for r, n in sorted(summary.items(), reverse=True))
            lines.append(f"累计：{sum(summary.values())} 抽（{detail}）")
        return "\n".join(lines)
