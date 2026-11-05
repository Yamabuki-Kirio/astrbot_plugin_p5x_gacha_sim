"""渲染层测试：十连/单抽出图的结构性断言。

    python -m pytest tests -q

这里只做「可稳定断言」的检查（尺寸、耗时、不抛异常、关键区域的颜色关系），
不跟参考截图做像素比对——素材不同，像素永远对不上。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.mechanics import GachaMechanics, PullResult  # noqa: E402
from src.core.models import Item, PityState  # noqa: E402
from src.core.registry import Registry  # noqa: E402
from src.render.renderer import (  # noqa: E402
    CARD_LAYOUT,
    DESIGN_H,
    DESIGN_W,
    Renderer,
    card_geometry,
)


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load()


@pytest.fixture(scope="module")
def renderer() -> Renderer:
    return Renderer()


def _r(item: Item, rarity: int | None = None, up: bool = False, index: int = 1) -> PullResult:
    return PullResult(item=item, rarity=rarity or item.rarity, is_up=up, index=index,
                      pity5_after=1, pity4_after=1)


def _ten(results: list[PullResult]) -> list[PullResult]:
    return [_r(result.item, result.rarity, result.is_up, i + 1) for i, result in enumerate(results)]


def _mixed(registry: Registry) -> list[PullResult]:
    banner = registry.banner("char_limited")
    five = list(banner.pool[5])
    four = list(banner.pool[4])
    two = list(banner.pool[2])
    picks = [five[0], four[0], five[1], two[0], four[1], five[0], two[1], four[2], two[2], four[3]]
    return [_r(item, item.rarity, up=(i == 0), index=i + 1) for i, item in enumerate(picks)]


def test_ten_render_size_and_speed(registry, renderer):
    results = _mixed(registry)
    started = time.perf_counter()
    image = renderer.render_ten(results)
    elapsed = time.perf_counter() - started
    assert image.size == (DESIGN_W, DESIGN_H)
    assert image.mode == "RGB"
    assert elapsed < 3.5, f"十连出图 {elapsed:.2f}s，超出 3.5s 上限"


def test_five_star_backdrop_is_blue(registry, renderer):
    """5★ 色带中部必须是蓝调（背后那团蓝影 + 深蓝底），不能被金色盖回。"""
    results = _mixed(registry)
    image = renderer.render_ten(results).convert("RGB")
    geometry = card_geometry(0, 5)
    (_, top), (_, _), (_, bottom), (_, _) = geometry.quad
    cx = (geometry.quad[0][0] + geometry.quad[2][0]) / 2
    cy = (top + bottom) / 2
    # 取卡片中上部（避开立绘与底部徽记）
    r, g, b = image.getpixel((int(cx - geometry.width * 0.30), int(cy - geometry.height * 0.25)))
    assert b > r + 30, f"5★ 中部应为蓝调，实际 {(r, g, b)}"


def test_layout_matches_reference_rhythm():
    """布局表：10 条色带，顶边高低错落（参考截图里相邻卡顶边差异明显）。"""
    assert len(CARD_LAYOUT) == 10
    tops = [card_geometry(i, 2).top for i in range(10)]
    assert len(set(tops)) > 4, "色带顶边应有明显高低差"
    bottoms = [card_geometry(i, 2).quad[2][1] for i in range(10)]
    assert max(bottoms) - min(bottoms) > 20, "色带底边应有高低差"


def test_first_and_last_card_are_visible():
    """首卡只被裁掉一点；末卡的顶边大部分落在画布内（底边为斜切，可越出）。"""
    first = card_geometry(0, 2)
    last = card_geometry(9, 2)
    assert first.quad[0][0] < 200, "第 1 张应贴住左边"
    top_left, top_right = last.quad[0][0], last.quad[1][0]
    visible = min(top_right, DESIGN_W) - max(top_left, 0)
    assert visible > (top_right - top_left) * 0.4, "第 10 张应有至少 40% 的顶边在画布内"


def test_missing_art_uses_silhouette(registry, renderer):
    """人格面具没有立绘：渲染必须走剪影兜底，且不抛异常。"""
    banner = registry.banner("char_standard")
    personas = [item for item in banner.pool.get(2, ()) if renderer.portrait(item) is None]
    assert personas, "测试前提：至少有一个缺图的人格面具"
    results = [_r(item, 2, index=i + 1) for i, item in enumerate(personas[:10])]
    image = renderer.render_ten(results)
    assert image.size == (DESIGN_W, DESIGN_H)


def test_empty_and_partial_results(registry, renderer):
    assert renderer.render_ten([]).size == (DESIGN_W, DESIGN_H)
    one = [_r(list(registry.banner("char_limited").pool[5])[0], 5, index=1)]
    # 只有一张时取布局表中间一段并居中，不该抛异常
    assert renderer.render_ten(one).size == (DESIGN_W, DESIGN_H)


def test_weapon_ten(registry, renderer):
    banner = registry.banner("weapon_limited")
    picks = list(banner.pool[5])[:5] + list(banner.pool[4])[:5]
    results = [_r(item, item.rarity, index=i + 1) for i, item in enumerate(picks)]
    assert renderer.render_ten(results, banner).size == (DESIGN_W, DESIGN_H)


def test_no_up_badge(renderer, registry):
    """截图里没有 UP 角标，渲染也不应再画红色三角。"""
    banner = registry.banner("char_limited")
    item = list(banner.pool[5])[0]
    results = [_r(item, 5, up=True, index=i + 1) for i in range(10)]
    image = renderer.render_ten(results).convert("RGB")
    region = image.crop((int(DESIGN_W * 0.55), 0, DESIGN_W, int(DESIGN_H * 0.10)))
    reds = sum(
        1
        for px in region.getdata()
        if px[0] > 180 and px[1] < 80 and px[2] < 90
    )
    assert reds < region.width * region.height * 0.02, "不应出现红色 UP 角标"


def test_reward_row_on_high_rarity_cards(registry, renderer):
    """5★/4★ 的奖励行应存在：高星卡片底部一带应出现金色像素。"""
    results = _mixed(registry)
    image = renderer.render_ten(results).convert("RGB")
    band = image.crop((0, int(DESIGN_H * 0.50), DESIGN_W, int(DESIGN_H * 0.72)))
    gold = sum(1 for px in band.getdata() if px[0] > 180 and px[1] > 140 and px[2] < 130)
    assert gold > 400, f"卡片底部金色像素只有 {gold}，奖励图标可能没画出来"


def test_single_render(registry, renderer):
    item = list(registry.banner("char_limited").pool[5])[0]
    image = renderer.render_single(_r(item, 5))
    assert image.size == (1200, 905)
    assert image.mode == "RGB"


def test_single_render_low_star(registry, renderer):
    item = list(registry.banner("char_standard").pool[2])[0]
    image = renderer.render_single(_r(item, 2))
    assert image.size == (1200, 905)


def test_persona_kind_is_forced(registry):
    """personas.json 没有 kind 字段，Banner 读进来时也必须识别为 persona。"""
    banner = registry.banner("char_limited")
    personas = [item for items in banner.pool.values() for item in items if item.id.startswith("persona:")]
    assert personas, "卡池里应有人格面具"
    assert all(item.kind == "persona" for item in personas)


def test_mechanics_outputs_render(registry, renderer):
    """机制层真实产出的十连结果可以直接交给渲染器。"""
    banner = registry.banner("char_limited")
    mech = GachaMechanics(__import__("random").Random(7))
    results, _state = mech.pull_many(banner, PityState(pity5=70), 10)
    assert renderer.render_ten(results, banner).size == (DESIGN_W, DESIGN_H)
