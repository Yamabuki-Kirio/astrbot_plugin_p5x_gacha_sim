from PIL import Image, ImageDraw, ImageChops, ImageStat
from src.core.mechanics import PullResult
from src.core.registry import Registry
from src.render.renderer import Renderer, foundation_geometry


def coverage(renderer, item):
    geo = foundation_geometry(4, item.rarity)
    result = PullResult(item, item.rarity, False, 1, 0, 0)
    art, position = renderer.art_layer(result, geo, 1)
    mask = Image.new("L", (1920, 1080))
    ImageDraw.Draw(mask).polygon(geo.quad, fill=255)
    alpha = Image.new("L", mask.size)
    alpha.paste(art.getchannel("A"), position)
    return ImageStat.Stat(ImageChops.multiply(alpha, mask)).sum[0] / ImageStat.Stat(mask).sum[0]


def test_native_cards_fill_the_result_strip():
    renderer, registry = Renderer(), Registry.load()
    for code in ("AEGIS", "FUKA", "JUNPEI"):
        item = registry.items["char:"+code]
        assert renderer._native_character_art(item, foundation_geometry(4, item.rarity), 1)
        assert coverage(renderer, item) > .90, code


def test_character_and_persona_cover_most_of_the_card():
    renderer, registry = Renderer(), Registry.load()
    items = [item for item in registry.items.values()
             if renderer._character_pair(item)]
    ratios = [coverage(renderer, item) for item in items]
    assert len(ratios) >= 60
    assert sum(ratios)/len(ratios) > .90


def test_native_cards_can_fall_back_when_assets_are_missing(tmp_path):
    renderer, registry = Renderer(), Registry.load()
    renderer.assets = tmp_path
    item = registry.items["char:AEGIS"]
    assert renderer._native_character_art(item, foundation_geometry(4, item.rarity), 1) is None
