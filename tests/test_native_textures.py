from pathlib import Path

from PIL import Image

from src.render.renderer import Renderer
from src.render.renderer import foundation_geometry
from src.core.models import Item


def test_runtime_webp_preferred_with_legacy_png_fallback(tmp_path):
    png = tmp_path / "texture.png"
    webp = tmp_path / "texture.webp"
    original = Image.new("RGBA", (32, 48), (70, 110, 180, 143))
    original.save(png)
    assert Renderer._runtime_asset(png) == png
    original.save(webp, lossless=True, exact=True)
    assert Renderer._runtime_asset(png) == webp
    assert Renderer._runtime_asset(webp) == webp
    assert Image.open(Renderer._runtime_asset(png)).convert("RGBA").tobytes() == original.tobytes()


def test_native_texture_does_not_double_shear():
    renderer = Renderer()
    image = Image.new("RGBA", (400, 900))
    quad = [(170, 10), (350, 10), (180, 838), (0, 838)]
    assert renderer._native_foundation(image, quad, 3, "电击", "persona", 1)
    # 原图自带约一半宽的透明斜边，映射后色带中线仍应处处不透明。
    for y in (40, 300, 600, 800):
        x = round(260 - 170 * (y-10) / 828)
        assert image.getpixel((x, y))[3] >= 254
    assert image.getpixel((390, 450))[3] == 0


def test_native_unknown_element_is_fixed_default():
    renderer = Renderer()
    quad = [(170, 10), (350, 10), (180, 838), (0, 838)]
    images = [Image.new("RGBA", (400, 900)) for _ in range(2)]
    renderer._native_foundation(images[0], quad, 3, "", "persona", 1)
    renderer._native_foundation(images[1], quad, 3, "万能", "persona", 1)
    assert images[0].tobytes() == images[1].tobytes()


def test_character_foundation_uses_rarity_background_not_element():
    renderer = Renderer()
    geo = foundation_geometry(4, 5)
    image, offset = renderer._foundation_card(geo, 1, 4, 5, "电击", "character")
    center = tuple(round(sum(p[i] for p in geo.quad)/4-offset[i]) for i in (0, 1))
    r, g, b, a = image.getpixel(center)
    assert b > r and a >= 254
    other, _ = renderer._foundation_card(geo, 1, 4, 5, "火焰", "character")
    assert image.tobytes() == other.tobytes()


def test_character_original_frame_follows_left_and_bottom():
    renderer = Renderer()
    geo = foundation_geometry(4, 5)
    image = Image.new("RGBA", (1920, 1080))
    renderer._character_frame(image, geo, 5)
    tl, tr, br, bl = geo.quad
    # 左侧中段与底边都有贴图像素，内侧不应被拉成整片品质色。
    left_x = (tl[0]+bl[0])/2
    left_y = (tl[1]+bl[1])/2
    assert image.crop((round(left_x)-3,round(left_y)-5,
                       round(left_x)+12,round(left_y)+5)).getbbox()
    bottom_x = (bl[0]+br[0])/2
    assert image.crop((round(bottom_x)-10,round(bl[1])-16,
                       round(bottom_x)+10,round(bl[1]))).getbbox()
    assert image.getpixel((round((tl[0]+tr[0]+bl[0]+br[0])/4),round(left_y)))[3] == 0


def test_character_pair_mapping():
    renderer = Renderer()
    for code in ("J&C", "SEPIA", "JOKER", "MARIAN", "LEON"):
        assert renderer._character_pair(Item("char:"+code, code, "character", 5))
    assert renderer._character_pair(Item("persona:J&C", "test", "persona", 3)) is None


def test_explicit_visual_mapping_files_exist():
    import json
    renderer = Renderer()
    root = renderer.assets / "character_layers"
    mapping = json.loads((root / "mapping.json").read_text(encoding="utf-8"))
    assert len(mapping) >= 63
    for code, entry in mapping.items():
        pair = renderer._character_pair(Item(code, entry["name"], "character", 5))
        assert pair is not None, code
        assert pair[0].stem == Path(entry["front"]).stem
        assert pair[0].is_file()
        if entry["back"]:
            assert pair[1].stem == Path(entry["back"]).stem and pair[1].is_file()
    assert mapping["char:KEY"]["front"] == "lihui-guaidao-kii.png"
    assert mapping["char:MESSA"]["front"] == "lihui-guaidao-doctor.png"
    assert mapping["char:MONA·Starlight"]["front"] == "PC067_01_01_04_01.png"


def test_persona_art_has_readable_size_without_old_oversizing():
    from src.core.registry import Registry
    from src.core.mechanics import PullResult
    renderer = Renderer()
    for item in Registry.load().items.values():
        if item.kind != "persona":
            continue
        original = renderer.portrait(item)
        if original is None:
            continue
        geo = foundation_geometry(3, item.rarity)
        result = PullResult(item,item.rarity,False,1,0,0)
        art,(x,y) = renderer.art_layer(result,geo,1)
        # 宽翼、圆形与细长主体采用不同尺寸；至少要保持可读的主体比例。
        assert art.height <= geo.height * 1.33 + 1
        assert art.width <= geo.width * 3.1 + 1
        assert max(art.width/geo.width, art.height/geo.height) >= .65, item.id
        # 实际卡槽中必须能看到足够的实体像素，不能只剩翼尖或尾巴。
        from PIL import Image, ImageDraw, ImageStat
        mask = Image.new("L", (1920,1080))
        ImageDraw.Draw(mask).polygon(geo.quad, fill=255)
        visible = Image.new("L",mask.size)
        visible.paste(art.getchannel("A"),(x,y))
        from PIL import ImageChops
        ratio = ImageStat.Stat(ImageChops.multiply(visible,mask)).sum[0] / max(1,ImageStat.Stat(art.getchannel("A")).sum[0])
        assert ratio > .10, item.id


def test_persona_background_matches_element_at_every_slot():
    renderer = Renderer()
    geo = foundation_geometry(3,3)
    for element in ("火焰","冰冻","电击","疾风","核热","念动","祝福","诅咒","物理"):
        first,_ = renderer._foundation_card(geo,1,0,3,element,"persona")
        second,_ = renderer._foundation_card(geo,1,9,3,element,"persona")
        assert first.tobytes() == second.tobytes()
    fire,_ = renderer._foundation_card(geo,1,0,3,"火焰","persona")
    ice,_ = renderer._foundation_card(geo,1,0,3,"冰冻","persona")
    assert fire.tobytes() != ice.tobytes()
