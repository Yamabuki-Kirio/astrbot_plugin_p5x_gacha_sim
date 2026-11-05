"""服务层集成测试：SQLite 落盘、历史、默认卡池、300 抽自选。

    python -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.models import PityState  # noqa: E402
from src.core.registry import Registry  # noqa: E402
from src.core.store import Store  # noqa: E402
from src.services.gacha_service import GachaService  # noqa: E402


@pytest.fixture()
def env(tmp_path):
    registry = Registry.load()
    store = Store(tmp_path / "test.sqlite3")
    service = GachaService(registry, store)
    yield registry, store, service
    store.close()


def test_ten_pull_persists_state_and_history(env):
    registry, store, service = env
    banner = registry.banner("char_limited")
    outcome = service.draw("qq", "u1", banner, 10)

    assert len(outcome.results) == 10
    assert outcome.cost == 10 * banner.cost
    state = store.load_state("qq", "u1", banner.pity_group)
    assert state.pulls == 10
    assert state.total_of(banner.id) == 10
    assert store.count_history("qq", "u1") == 10


def test_pity_groups_are_independent(env):
    registry, store, service = env
    limited = registry.banner("char_limited")
    standard = registry.banner("char_standard")
    service.draw("qq", "u1", limited, 10)
    service.draw("qq", "u1", standard, 10)

    assert store.load_state("qq", "u1", limited.pity_group).total_of(limited.id) == 10
    assert store.load_state("qq", "u1", standard.pity_group).total_of(standard.id) == 10
    assert limited.pity_group != standard.pity_group


def test_history_pagination(env):
    registry, store, service = env
    banner = registry.banner("char_limited")
    for _ in range(3):
        service.draw("qq", "u1", banner, 10)

    text = service.format_history("qq", "u1", banner, 1)
    assert "共 30 条" in text
    page2 = service.format_history("qq", "u1", banner, 2)
    assert "2/" in page2


def test_default_banner_roundtrip(env):
    registry, store, service = env
    assert store.get_default_banner("qq", "u1") is None
    store.set_default_banner("qq", "u1", "weapon_limited")
    assert store.get_default_banner("qq", "u1") == "weapon_limited"


def test_selector_requires_300_pulls(env):
    registry, store, service = env
    banner = registry.banner("char_standard")
    target = banner.candidates(5)[0]
    with pytest.raises(ValueError):
        service.select_character("qq", "u1", banner, target.id)

    state = PityState(totals={banner.id: 300}, pulls=300)
    store.save_state("qq", "u1", banner.pity_group, state)
    name = service.select_character("qq", "u1", banner, target.id)
    assert name == target.name
    after = store.load_state("qq", "u1", banner.pity_group)
    assert after.total_of(banner.id) == 0, "自选后应扣掉 300 抽"

    with pytest.raises(ValueError):
        service.select_character("qq", "u1", banner, registry.banner("char_limited").candidates(5)[0].id)


def test_format_pity_mentions_guarantee(env):
    registry, store, service = env
    banner = registry.banner("weapon_limited")
    text = service.format_pity(banner, PityState(guaranteed5=True, pity5=12))
    assert "必定是当期 UP" in text
    assert "140" in text


def test_record_history_off_keeps_pity(env):
    registry, store, service = env
    service.record_history = False
    banner = registry.banner("char_limited")
    service.draw("qq", "u1", banner, 10)
    assert store.count_history("qq", "u1") == 0
    assert store.load_state("qq", "u1", banner.pity_group).total_of(banner.id) == 10


def test_clear_user(env):
    registry, store, service = env
    banner = registry.banner("char_limited")
    store.set_default_banner("qq", "u1", banner.id)
    service.draw("qq", "u1", banner, 10)
    store.clear_user("qq", "u1")
    assert store.count_history("qq", "u1") == 0
    assert store.get_default_banner("qq", "u1") is None
