"""抽卡服务：把「读状态 → 抽 → 写状态 + 历史」包成一个原子操作，并负责文案。

AstrBot 侧只调用这里的函数，不直接碰数据库和随机数。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from ..core.mechanics import GachaMechanics, PullResult
from ..core.models import Banner, PityState, Item
from ..core.collection import collectible, OwnedItem
from ..core.registry import Registry
from ..core.store import Store


@dataclass(frozen=True)
class DailyQuota:
    day: str
    used: int
    bonus: int
    signed: bool
    base: int

    @property
    def remaining(self):
        return max(0, self.base + self.bonus - self.used)


@dataclass
class DrawOutcome:
    banner: Banner
    results: list[PullResult]
    state: PityState
    cost: int
    elapsed_ms: int
    remaining: int = 0
    overflow_bonus: int = 0

    @property
    def five_stars(self) -> list[PullResult]:
        return [r for r in self.results if r.rarity == 5]

    @property
    def four_stars(self) -> list[PullResult]:
        return [r for r in self.results if r.rarity == 4]


class GachaService:
    def __init__(self, registry: Registry, store: Store, record_history: bool = True,
                 daily_pulls: int = 10, signin_bonus: int = 10, clock=None):
        self.registry = registry
        self.store = store
        self.record_history = record_history
        if isinstance(daily_pulls, bool) or not isinstance(daily_pulls, int) or daily_pulls < 0:
            raise ValueError("每日基础抽数必须是非负整数")
        if isinstance(signin_bonus, bool) or not isinstance(signin_bonus, int) or signin_bonus < 0:
            raise ValueError("签到奖励抽数必须是非负整数")
        self.daily_pulls = daily_pulls
        self.signin_bonus = signin_bonus
        self.clock = clock or time.time
        self.mechanics = GachaMechanics()
        # 抽卡是「读改写」，串行化避免同一用户并发抽卡时保底计数丢失
        self._lock = threading.Lock()
        self.store.bootstrap_collection(self.registry.items)

    # ------------------------------------------------------------------
    def draw(self, platform_id: str, user_id: str, banner: Banner, count: int) -> DrawOutcome:
        if count not in (1, 10):
            raise ValueError("只支持单抽或十连")
        if not banner.enabled:
            raise ValueError(f"卡池「{banner.name}」已停用")
        started = time.perf_counter()
        with self._lock, self.store.transaction():
            quota = self.quota_of(platform_id, user_id)
            if quota.remaining < count:
                tip = "可发送 /签到 领取今日奖励。" if not quota.signed else "今日已签到，请在北京时间零点刷新后再来。"
                raise ValueError(f"今日剩余 {quota.remaining} 抽，本次需要 {count} 抽。{tip}")
            state = self.store.load_state(platform_id, user_id, banner.pity_group)
            results, new_state = self.mechanics.pull_many(banner, state, count)
            self.store.save_state(platform_id, user_id, banner.pity_group, new_state)
            if self.record_history:
                self.store.add_history(
                    platform_id,
                    user_id,
                    banner.id,
                    [(r.item.id, r.item.name, r.rarity, r.is_up) for r in results if collectible(r.item)],
                )
            overflow_bonus = sum(self.store.add_owned(platform_id, user_id, r.item) for r in results) * 10
            self.store.save_daily(platform_id, user_id, quota.day, quota.used + count,
                                  quota.bonus + overflow_bonus, quota.signed)
        return DrawOutcome(
            banner=banner,
            results=results,
            state=new_state,
            cost=banner.cost * count,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            remaining=quota.remaining-count+overflow_bonus,
            overflow_bonus=overflow_bonus,
        )

    # ------------------------------------------------------------------
    def _day(self):
        return datetime.fromtimestamp(self.clock(), timezone(timedelta(hours=8))).date().isoformat()

    def quota_of(self, platform_id, user_id):
        row = self.store.daily_status(platform_id, user_id, self._day())
        return DailyQuota(row["day"], row["used"], row["bonus"], bool(row["signed"]), self.daily_pulls)

    def signin(self, platform_id, user_id):
        with self._lock, self.store.transaction():
            quota = self.quota_of(platform_id, user_id)
            if quota.signed:
                return quota, False
            self.store.save_daily(platform_id, user_id, quota.day, quota.used,
                                  quota.bonus + self.signin_bonus, True)
            return DailyQuota(quota.day, quota.used, quota.bonus + self.signin_bonus, True, self.daily_pulls), True

    def refresh_all(self):
        with self._lock, self.store.transaction():
            return self.store.refresh_daily_all(self._day(), 10, self.daily_pulls)

    def team_of(self, platform_id, user_id):
        owned = []
        for row in self.store.owned_items(platform_id, user_id):
            item = self.registry.item(row['item_id']) or Item(
                id=row['item_id'], name=row['item_name'], kind=row['kind'], rarity=row['rarity'])
            owned.append(OwnedItem(item, row['copies']))
        return tuple(owned)

    def state_of(self, platform_id: str, user_id: str, banner: Banner) -> PityState:
        return self.store.load_state(platform_id, user_id, banner.pity_group)

    def select_character(self, platform_id: str, user_id: str, banner: Banner, item_id: str) -> str:
        """常驻池 300 抽自选：满足抽数就发一个 5★ 并把计数清零。"""
        if not banner.selector_at:
            raise ValueError("该卡池没有自选机制")
        with self._lock, self.store.transaction():
            state = self.state_of(platform_id, user_id, banner)
            total = state.total_of(banner.id)
            if total < banner.selector_at:
                raise ValueError(f"还没有到 {banner.selector_at} 抽（当前 {total} 抽）")
            item = self.registry.item(item_id)
            if item is None or item.rarity != 5 or item not in banner.candidates(5):
                raise ValueError("只能从本卡池的 5★ 候选里选")
            if self.record_history:
                self.store.add_history(platform_id, user_id, banner.id, [(item.id, item.name, 5, False)])
            overflow = self.store.add_owned(platform_id, user_id, item)
            self.store.save_state(
                platform_id, user_id, banner.pity_group, state.with_total(banner.id, total - banner.selector_at))
            if overflow:
                quota = self.quota_of(platform_id, user_id)
                self.store.save_daily(platform_id, user_id, quota.day, quota.used, quota.bonus+10, quota.signed)
            return item.name + ("（满阶重复，返还10抽）" if overflow else "")

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
        if outcome.overflow_bonus:
            lines.append(f"满阶重复返还 {outcome.overflow_bonus} 抽，已加入今日额度")
        return "\n".join(lines)

    def format_single(self, outcome: DrawOutcome) -> str:
        result = outcome.results[0]
        return "\n".join(
            [
                f"【{outcome.banner.name}】单抽结果",
                self.format_result_line(result),
                f"—— 消耗 {outcome.cost} 晶珀",
                self.format_pity_short(outcome.banner, outcome.state),
                *([f"满阶重复返还 {outcome.overflow_bonus} 抽，已加入今日额度"] if outcome.overflow_bonus else []),
            ]
        )

    @staticmethod
    def format_pity_short(banner: Banner, state: PityState) -> str:
        hard5 = banner.hard_pity.get(5, 80)
        hard4 = banner.hard_pity.get(4, 10)
        text = f"5★ 保底 {state.pity5}/{hard5}（还差 {hard5 - state.pity5} 抽） · 4★ {state.pity4}/{hard4}"
        if banner.has_off_rate(5):
            text += " · 大保底：" + ("已触发，下次 5★ 必为 UP" if state.guaranteed5 else "未触发")
        text += f" · 共享累计 {state.pulls} 抽"
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
        lines.append(f"共享累计 {state.pulls} 抽（同类限定池互通）")
        if state.guaranteed5 and not banner.rate_up.get(5):
            lines.append("已保存角色/武器 UP 大保底，切换指定目标后生效；本池五星不消耗该资格。")
        lines.append(f"本池累计 {state.total_of(banner.id)} 抽（跨期继承：{banner.pity_group}）")
        if banner.selector_at:
            total = state.total_of(banner.id)
            lines.append(f"常驻自选：{banner.selector_at} 抽可选一个 5★，当前 {total} 抽")
        return "\n".join(lines)

    def format_history(self, platform_id: str, user_id: str, banner: Banner | None, page: int, page_size: int = 10) -> str:
        banner_id = banner.id if banner else None
        total = self.store.count_history(platform_id, user_id, banner_id)
        if total == 0:
            return "还没有四、五星角色或武器的抽卡记录。"
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(max(1, page), pages)
        rows = self.store.history(platform_id, user_id, page_size, (page - 1) * page_size, banner_id)
        lines = [f"四五星角色/武器记录（{page}/{pages} 页，共 {total} 条）"]
        for row in rows:
            stamp = time.strftime("%m-%d %H:%M", time.localtime(row["created_at"]))
            stars = "★" * row["rarity"]
            up = " UP" if row["is_up"] else ""
            lines.append(f"{stamp}  {stars} {row['item_name']}{up}")
        summary = self.store.rarity_summary(platform_id, user_id, banner_id)
        if summary:
            detail = " · ".join(f"{r}★×{n}" for r, n in sorted(summary.items(), reverse=True))
            lines.append(f"已记录：{sum(summary.values())} 次四五星获得（{detail}）")
        return "\n".join(lines)
