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
    foundation_geometry,
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
    """最高星结果排进中央后，其底版必须是蓝调。"""
    results = _mixed(registry)
    image = renderer.render_ten(results).convert("RGB")
    geometry = card_geometry(4, 2)
    (_, top), (_, _), (_, bottom), (_, _) = geometry.quad
    cx = (geometry.quad[0][0] + geometry.quad[2][0]) / 2
    cy = (top + bottom) / 2
    # 取卡片中上部（避开立绘与底部徽记）
    r, g, b = image.getpixel((int(cx), int(cy)))
    assert b > r + 30, f"5★ 中部应为蓝调，实际 {(r, g, b)}"


def test_layout_matches_reference_rhythm():
    """布局表：10 条色带，顶边高低错落（参考截图里相邻卡顶边差异明显）。"""
    assert len(CARD_LAYOUT) == 10
    tops = [card_geometry(i, 2).top for i in range(10)]
    assert len(set(tops)) > 4, "色带顶边应有明显高低差"
    bottoms = [card_geometry(i, 2).quad[2][1] for i in range(10)]
    assert len(set(bottoms)) == 1, "底版的底边应齐平，额外黑边再统一向下延长"


def test_foundation_cards_do_not_overlap():
    """十个底版之间必须留出黑缝，顶边和底边都不能相互覆盖。"""
    cards = [card_geometry(i, 2) for i in range(10)]
    for left, right in zip(cards, cards[1:]):
        assert left.quad[1][0] <= right.quad[0][0]
        assert left.quad[2][0] <= right.quad[3][0]


def test_first_and_last_card_are_visible():
    """首卡只被裁掉一点；末卡的顶边大部分落在画布内（底边为斜切，可越出）。"""
    first = card_geometry(0, 2)
    last = card_geometry(9, 2)
    assert first.quad[3][0] < 220, "第 1 张的左下边应贴近参考图左侧"
    top_left, top_right = last.quad[0][0], last.quad[1][0]
    visible = min(top_right, DESIGN_W) - max(top_left, 0)
    assert visible > (top_right - top_left) * 0.4, "第 10 张应有至少 40% 的顶边在画布内"


def test_cards_lean_down_to_the_left_like_reference():
    """参考图的色带由右上斜向左下，底边不能画到顶边右侧。"""
    for index in range(10):
        geometry = card_geometry(index, 2)
        assert geometry.quad[3][0] < geometry.quad[0][0]


def test_result_has_no_surrounding_hud(registry, renderer):
    """用户要求仅背景与结果：顶部资源栏区域应与纯背景保持一致。"""
    results = _mixed(registry)
    rendered = renderer.render_ten(results).convert("RGB")
    background = renderer._background((DESIGN_W, DESIGN_H)).convert("RGB")
    assert rendered.crop((1800, 0, 1920, 70)).tobytes() == background.crop((1800, 0, 1920, 70)).tobytes()


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


def test_high_rarity_is_centered_without_changing_geometry(registry, renderer):
    """星级会改变底色与辉光，但只能重新分配固定卡位，不能改变几何。"""
    results = _mixed(registry)
    changed = [_r(result.item, 2, index=i + 1) for i, result in enumerate(results)]
    arranged = renderer._centered_result_slots(results)
    assert arranged[4].rarity == max(result.rarity for result in results)
    assert renderer.render_ten(results).tobytes() != renderer.render_ten(changed).tobytes()


def test_foundation_size_increases_with_rarity():
    sizes = [foundation_geometry(4, rarity) for rarity in (2, 3, 4, 5)]
    assert sizes[0].width == sizes[1].width == sizes[2].width
    assert sizes[0].height == sizes[1].height == sizes[2].height
    assert sizes[3].width > sizes[2].width
    assert sizes[3].height > sizes[2].height


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
