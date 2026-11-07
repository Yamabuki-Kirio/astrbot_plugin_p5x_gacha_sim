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
    """冰冻属性使用原生蓝底纹；星级不应覆盖属性底色。"""
    geometry = foundation_geometry(4, 5)
    image, offset = renderer._foundation_card(geometry, 1, 4, 5, "冰冻")
    cx = sum(p[0] for p in geometry.quad) / 4 - offset[0]
    cy = sum(p[1] for p in geometry.quad) / 4 - offset[1]
    r, g, b, _ = image.getpixel((int(cx), int(cy)))
    assert b > r + 30, f"5★ 中部应为蓝调，实际 {(r, g, b)}"


def test_layout_matches_reference_rhythm():
    """布局表：10 条色带，顶边高低错落（参考截图里相邻卡顶边差异明显）。"""
    assert len(CARD_LAYOUT) == 10
    tops = [card_geometry(i, 2).top for i in range(10)]
    assert len(set(tops)) > 4, "色带顶边应有明显高低差"
    bottoms = [card_geometry(i, 2).quad[2][1] for i in range(10)]
    assert len(set(bottoms)) > 4, "底边同样需要错落，不排成整齐卡片"


def test_foundation_cards_do_not_overlap():
    """基础槽位允许小幅压边，由黑线分隔，不得大面积重叠。"""
    cards = [card_geometry(i, 2) for i in range(10)]
    for left, right in zip(cards, cards[1:]):
        assert left.quad[1][0] - right.quad[0][0] <= 20
        assert left.quad[2][0] - right.quad[3][0] <= 20


def test_no_rewards_or_artificial_backdrop(registry, renderer, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("结果页不应调用奖励、标识或人工蓝影")
    for name in ("_result_rewards", "_card_emblem", "_five_backdrop"):
        monkeypatch.setattr(renderer, name, forbidden)
    renderer.render_ten(_mixed(registry))
    renderer.render_single(_mixed(registry)[0])


def test_only_high_rarity_has_glow(renderer):
    from PIL import Image
    for rarity in (2, 3, 4, 5):
        canvas = Image.new("RGBA", (DESIGN_W, DESIGN_H))
        renderer._five_flare(canvas, foundation_geometry(4, rarity), 1, rarity)
        assert (canvas.getbbox() is not None) == (rarity >= 4)


def test_canvas_matches_reference_widescreen_aspect():
    assert abs(DESIGN_W / DESIGN_H - 1280 / 582) < .001


def test_effect_limits_and_stable_identity(renderer):
    phase = renderer._effect_phase("char:JOKER", 4)
    assert phase == renderer._effect_phase("char:JOKER", 4)
    assert phase != renderer._effect_phase("char:JOKER", 5)
    assert phase != renderer._effect_phase("char:MONA", 4)
    for rarity, count in ((2,0),(3,0),(4,2),(5,3)):
        segments = renderer._effect_segments(phase, rarity)
        assert len(segments) == count
        assert all(0 <= lo < hi <= 1 and hi-lo <= .28 for _,lo,hi in segments)


def test_deterministic_output_and_scaled_framing(registry, renderer):
    from PIL import Image, ImageChops, ImageOps
    results = _mixed(registry)
    first = renderer.render_ten(results)
    assert renderer.render_ten(results).tobytes() == first.tobytes()
    small = renderer.render_ten(results, size=(960,540))
    expected = ImageOps.pad(first, (960,540), Image.Resampling.LANCZOS, color=(5,6,9))
    assert ImageChops.difference(small, expected).getbbox() is None
    square = renderer.render_ten(results, size=(960,960))
    expected_square = ImageOps.pad(first, (960,960), Image.Resampling.LANCZOS, color=(5,6,9))
    assert square.tobytes() == expected_square.tobytes()


def test_background_preserves_source_aspect(tmp_path):
    from PIL import Image, ImageDraw
    source = Image.new("RGB", (1920,1080), (8,8,8))
    ImageDraw.Draw(source).ellipse((860,440,1060,640), fill=(220,30,20))
    source.save(tmp_path / "p5x-gacha-background-v1.png")
    image = Renderer(assets_dir=tmp_path)._background((960,960))
    mask = image.getchannel("R").point(lambda value: 255 if value>100 else 0)
    left, top, right, bottom = mask.getbbox()
    assert abs((right-left)-(bottom-top)) <= 1


def test_weapon_palette_ignores_persona_element(renderer):
    geo = foundation_geometry(0, 3)
    red, _ = renderer._foundation_card(geo, 1, 0, 3, "火焰", "weapon")
    blue, _ = renderer._foundation_card(geo, 1, 9, 3, "冰冻", "weapon")
    assert red.tobytes() == blue.tobytes()
    persona, _ = renderer._foundation_card(geo, 1, 0, 3, "冰冻", "persona")
    assert red.tobytes() != persona.tobytes()


def test_blue_cutline_stays_above_effects(registry, renderer):
    expected = renderer._background((DESIGN_W,DESIGN_H)).getpixel((1900,round(DESIGN_H*990/1080)))[:3]
    assert expected == (0,38,196)
    assert renderer.render_ten(_mixed(registry)).getpixel((1900,round(DESIGN_H*990/1080))) == expected


def test_persona_elements_have_sources(registry):
    personas = [item for item in registry.items.values() if item.kind == "persona"]
    assert len(personas) == 60
    assert all(item.element and item.meta.get("element_source") for item in personas)


def test_backlight_does_not_tint_low_strips(registry, renderer, monkeypatch):
    results = _mixed(registry)
    positions = []
    original = renderer._high_star_backlight
    def capture(canvas, geometries, arranged, scale):
        positions.extend((geo, result) for geo,result in zip(geometries, arranged) if result.rarity < 4)
        original(canvas, geometries, arranged, scale)
    monkeypatch.setattr(renderer, "_high_star_backlight", capture)
    with_light = renderer.render_ten(results)
    monkeypatch.setattr(renderer, "_high_star_backlight", lambda *args: None)
    monkeypatch.setattr(renderer, "_five_flare", lambda *args: None)
    without = renderer.render_ten(results)
    for geo, _ in positions:
        # 不只测中心：检查低星整条内部网格，包含靠近高星的边缘。
        for t in (.1,.3,.5,.7,.85):
            left = geo.quad[0][0]*(1-t)+geo.quad[3][0]*t
            y = int(geo.top+geo.height*t)
            for fraction in (.15,.5,.85):
                x = int(left+geo.width*fraction)
                assert with_light.getpixel((x,y)) == without.getpixel((x,y))


def test_final_black_separators_survive_glow(registry, renderer, monkeypatch):
    original = renderer._draw_separators
    checked = []
    def verify(canvas, geometries, scale, rarities=None):
        from PIL import Image, ImageDraw
        original(canvas, geometries, scale, rarities)
        for index, geometry in enumerate(geometries):
            assert all(0 <= x < DESIGN_W and 0 <= y < DESIGN_H for x,y in geometry.quad)
            if rarities and rarities[index] < 4:
                assert all(0 <= x < DESIGN_W and 0 <= y < DESIGN_H
                           for x,y in renderer._low_star_foot(geometry, scale))
            occluded = Image.new("L", canvas.size)
            for front in geometries[index+1:]:
                ImageDraw.Draw(occluded).polygon([(int(x*scale), int(y*scale)) for x,y in front.quad], fill=255)
            for start, end in ((1, 2), (2, 3)):
                if start == 2 and rarities and rarities[index] < 4:
                    continue
                a, b = geometry.quad[start], geometry.quad[end]
                for t in (.25, .5, .75):
                    x = int((a[0] + (b[0]-a[0])*t)*scale)
                    y = int((a[1] + (b[1]-a[1])*t)*scale)
                    if occluded.getpixel((x, y)):
                        continue
                    assert max(canvas.getpixel((x, y))[:3]) < 12
        checked.append(True)
    monkeypatch.setattr(renderer, "_draw_separators", verify)
    renderer.render_ten(_mixed(registry))
    assert checked


def test_hidden_border_does_not_cross_front_strip(renderer):
    from PIL import Image
    from src.render.renderer import CardGeometry
    back = CardGeometry(((20, 20), (100, 20), (100, 180), (20, 180)), 80, 160)
    front = CardGeometry(((90, 45), (170, 45), (170, 160), (90, 160)), 80, 115)
    canvas = Image.new("RGBA", (200, 200), (80, 90, 100, 255))
    renderer._draw_separators(canvas, [back, front], 1)
    assert canvas.getpixel((100, 80))[:3] == (80, 90, 100)
    assert canvas.getpixel((90, 80))[:3] == (80, 90, 100)
    assert canvas.getpixel((170, 80))[:3] == (2, 2, 4)


def test_strip_has_no_top_or_left_black_border(renderer):
    from PIL import Image
    from src.render.renderer import CardGeometry
    geo = CardGeometry(((20, 20), (100, 20), (100, 180), (20, 180)), 80, 160)
    canvas = Image.new("RGBA", (200, 200), (80, 90, 100, 255))
    renderer._draw_separators(canvas, [geo], 1)
    assert canvas.getpixel((60, 20))[:3] == (80, 90, 100)
    assert canvas.getpixel((20, 80))[:3] == (80, 90, 100)
    base, offset = renderer._foundation_card(geo, 1, 0, 2)
    for x, y in ((60, 21), (21, 80)):
        assert max(base.getpixel((x-offset[0], y-offset[1]))[:3]) > 20


def test_low_star_bottom_is_triangular_only(renderer):
    from src.render.renderer import CardGeometry
    geo = CardGeometry(((50, 20), (190, 20), (150, 280), (10, 280)), 140, 260)
    foot = renderer._low_star_foot(geo, 1)
    assert foot[0] == (10, 298)
    assert foot[1] == (150, 298)
    assert renderer._low_star_foot(geo, .5)[1] == (75, 149)
    for rarity in (2, 3, 4, 5):
        base, offset = renderer._foundation_card(geo, 1, 0, rarity)
        # 楔形左侧仍是颜色，右侧同高位置已进入三角黑衬底。
        left = base.getpixel((40-offset[0], 265-offset[1]))
        right = base.getpixel((135-offset[0], 265-offset[1]))
        assert max(left[:3]) > 20
        assert (max(right[:3]) < 12) == (rarity in (2, 3))


def test_all_low_results_do_not_call_glow(registry, renderer, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("低星不应绘制光效")
    monkeypatch.setattr(renderer, "_five_flare", forbidden)
    items = list(registry.banner("char_standard").pool[2])
    renderer.render_ten([_r(items[i % len(items)], 2, index=i+1) for i in range(10)])


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


def test_persona_art_is_complete(registry, renderer):
    """当前 2★/3★人格面具应全部命中真实立绘，不再走统一剪影。"""
    banner = registry.banner("char_standard")
    personas = [item for rarity in (2, 3) for item in banner.pool.get(rarity, ())]
    assert personas
    assert all(renderer.portrait(item) is not None for item in personas)
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
    assert arranged[5].rarity == max(result.rarity for result in results)
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


def test_gold_and_purple_effects_have_soft_continuous_bloom(renderer):
    from PIL import Image,ImageStat
    energies=[]
    geometry=foundation_geometry(4,5)
    for rarity in (4,5):
        effect=Image.new('RGBA',(DESIGN_W,DESIGN_H))
        renderer._five_flare(effect,geometry,1,rarity,'char:demo',4)
        alpha=effect.getchannel('A')
        hist=alpha.histogram()
        assert sum(hist[1:180])>1500
        # 泛光来自分级透明度，不使用白色星形亮芯。
        assert sum(1 for r,g,b,a in effect.getdata() if min(r,g,b)>210 and a>220)==0
        energies.append(ImageStat.Stat(alpha).sum[0])
    assert energies[1]>energies[0]


def test_external_glow_never_overlays_card_faces(registry,renderer,monkeypatch):
    results=_mixed(registry)
    geometries=[]
    original=renderer._high_star_backlight
    def capture(canvas,geos,arranged,scale):
        geometries.extend(geos)
        original(canvas,geos,arranged,scale)
    monkeypatch.setattr(renderer,'_high_star_backlight',capture)
    lit=renderer.render_ten(results)
    monkeypatch.setattr(renderer,'_high_star_backlight',lambda *args:None)
    plain=renderer.render_ten(results)
    for geo in geometries:
        for t in (.15,.3,.45,.6,.8):
            left=geo.quad[0][0]*(1-t)+geo.quad[3][0]*t
            y=int(geo.top+geo.height*t)
            for f in (.2,.4,.6,.8):
                x=int(left+geo.width*f)
                assert lit.getpixel((x,y))==plain.getpixel((x,y))
