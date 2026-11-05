"""机制单元测试：不依赖 AstrBot，也不联网。

    python -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.mechanics import GachaMechanics  # noqa: E402
from src.core.models import Banner, Item, PityState, PoolError  # noqa: E402
from src.core.registry import Registry  # noqa: E402


class AlwaysMiss:
    """random() 恒为 0.999…，用于强制吃满保底。"""

    def random(self) -> float:
        return 0.999999

    def choice(self, seq):
        return seq[0]


class AlwaysHit:
    def random(self) -> float:
        return 0.0

    def choice(self, seq):
        return seq[-1]


def make_banner(**overrides) -> Banner:
    items = {
        "5": [Item("up5", "UP5", "character", 5), Item("off5", "OFF5", "character", 5)],
        "4": [Item("up4", "UP4", "character", 4), Item("off4", "OFF4", "character", 4)],
        "3": [Item("p3", "P3", "persona", 3)],
        "2": [Item("p2", "P2", "persona", 2)],
    }
    data = {
        "id": "test",
        "name": "测试池",
        "kind": "character",
        "pity_group": "test",
        "cost": 150,
        "rates": {"5": 0.008, "4": 0.062, "3": 0.03, "2": 0.90},
        "up_rate": {"5": 0.5, "4": 0.5},
        "hard_pity": {"5": 80, "4": 10},
        "pool": {k: [i.id for i in v] for k, v in items.items()},
        "rate_up": {"5": ["up5"], "4": ["up4"]},
    }
    data.update(overrides)
    return Banner.from_dict(data, {i.id: i for v in items.values() for i in v})


# ----------------------------------------------------------------------
# 卡池校验
# ----------------------------------------------------------------------
def test_rates_must_sum_to_one():
    with pytest.raises(PoolError):
        make_banner(rates={"5": 0.008, "4": 0.062, "3": 0.03, "2": 0.5})


def test_up_must_exist_in_pool():
    with pytest.raises(PoolError):
        make_banner(rate_up={"5": ["nope"], "4": []})


def test_shipped_banners_are_valid():
    registry = Registry.load()
    assert len(registry.enabled_banners()) >= 4
    for banner in registry.enabled_banners():
        assert banner.candidates(5)
        assert abs(sum(banner.rates.get(r, 0) for r in (5, 4, 3, 2)) - 1) < 1e-9


# ----------------------------------------------------------------------
# 保底
# ----------------------------------------------------------------------
def test_hard_pity_80():
    mech = GachaMechanics(AlwaysMiss())
    banner = make_banner()
    state = PityState()
    for n in range(1, 81):
        result, state = mech.pull(banner, state)
        if n < 80:
            assert result.rarity < 5, f"第 {n} 抽不该出 5★"
        else:
            assert result.rarity == 5, "第 80 抽必须出 5★"
    assert state.pity5 == 0


def test_four_star_pity_every_10():
    mech = GachaMechanics(AlwaysMiss())
    banner = make_banner()
    state = PityState()
    for n in range(1, 11):
        result, state = mech.pull(banner, state)
        if n < 10:
            assert result.rarity < 4, f"第 {n} 抽不该出 4★"
        else:
            assert result.rarity == 4, "第 10 抽必须出 4★"
    assert state.pity4 == 0


def test_five_star_resets_four_star_pity():
    mech = GachaMechanics(AlwaysMiss())
    banner = make_banner()
    state = PityState(pity5=79, pity4=9)  # 下一抽必出 5★
    result, state = mech.pull(banner, state)
    assert result.rarity == 5
    assert state.pity4 == 0 and state.pity5 == 0


def test_weapon_banner_pity_70():
    mech = GachaMechanics(AlwaysMiss())
    registry = Registry.load()
    banner = registry.banner("weapon_standard")
    state = PityState()
    for n in range(1, 71):
        result, state = mech.pull(banner, state)
        if n < 70:
            assert result.rarity < 5
        else:
            assert result.rarity == 5


def test_five_rate_zero_until_hard_pity():
    banner = make_banner()
    assert GachaMechanics.five_rate(PityState(pity5=0), banner) == pytest.approx(0.008)
    assert GachaMechanics.five_rate(PityState(pity5=78), banner) == pytest.approx(0.008)
    assert GachaMechanics.five_rate(PityState(pity5=79), banner) == 1.0


def test_soft_pity_increments():
    banner = make_banner(soft_pity=[{"start": 66, "end": 70, "increment": 0.04}])
    # pity5 记录「已抽发数」，所以 pity5=65 时正在抽第 66 发，软保底生效
    assert GachaMechanics.five_rate(PityState(pity5=64), banner) == pytest.approx(0.008)
    assert GachaMechanics.five_rate(PityState(pity5=65), banner) == pytest.approx(0.048)
    assert GachaMechanics.five_rate(PityState(pity5=69), banner) == pytest.approx(0.208)
    # 区间结束后不再增长
    assert GachaMechanics.five_rate(PityState(pity5=70), banner) == pytest.approx(0.208)


# ----------------------------------------------------------------------
# 小保底 / UP
# ----------------------------------------------------------------------
def test_guarantee_after_losing_fifty_fifty():
    banner = make_banner()
    # 第一次 5★ 走「歪」分支：guaranteed=False，随机值 > up_rate
    class LoseThenWin(AlwaysMiss):
        pass

    mech = GachaMechanics(LoseThenWin())
    state = PityState(guaranteed5=True, pity5=79)  # 直接进入必中状态
    result, state = mech.pull(banner, state)
    assert result.rarity == 5
    assert result.is_up is True, "guaranteed5 为真时必须出 UP"
    assert state.guaranteed5 is False, "拿到 UP 后小保底清零"


def test_losing_sets_guarantee():
    banner = make_banner()

    class RollHigh:
        def random(self):
            return 0.9999  # 5★ 只可能来自硬保底，UP 判定必然失败

        def choice(self, seq):
            return seq[0]

    mech = GachaMechanics(RollHigh())
    state = PityState(pity5=79)
    result, state = mech.pull(banner, state)
    assert result.rarity == 5
    assert result.is_up is False
    assert state.guaranteed5 is True


def test_standard_banner_never_up():
    registry = Registry.load()
    banner = registry.banner("char_standard")
    mech = GachaMechanics(AlwaysHit())
    state = PityState()
    results, _ = mech.pull_many(banner, state, 100)
    assert all(not r.is_up for r in results)


# ----------------------------------------------------------------------
# 状态与继承
# ----------------------------------------------------------------------
def test_pity_carries_between_banners_same_group():
    registry = Registry.load()
    a = registry.banner("char_limited")
    b = registry.banner("char_standard")
    mech = GachaMechanics(AlwaysMiss())
    state = PityState(pity5=70, pity4=3)
    _, state = mech.pull(a, state)
    assert state.pity5 == 71
    _, state = mech.pull(b, state)  # 换池子，保底跟着走
    assert state.pity5 == 72
    assert state.total_of(a.id) == 1 and state.total_of(b.id) == 1


def test_state_roundtrip():
    state = PityState(pity5=12, pity4=3, guaranteed5=True, totals={"a": 5}, pulls=42)
    assert PityState.from_dict(state.to_dict()) == state


def test_ten_pull_has_at_least_one_four_star():
    """十连至少一个 4★ 及以上——4★ 保底每 10 抽一次的直接结果。"""
    registry = Registry.load()
    banner = registry.banner("char_limited")
    mech = GachaMechanics(AlwaysMiss())
    results, _ = mech.pull_many(banner, PityState(), 10)
    assert any(r.rarity >= 4 for r in results)
