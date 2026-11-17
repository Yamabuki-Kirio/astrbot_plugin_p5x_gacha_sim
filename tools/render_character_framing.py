"""渲染角色裁切验收图；不启动 AstrBot、不改动抽卡数据。"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.registry import Registry
from src.core.mechanics import PullResult
from src.render.renderer import Renderer, CardGeometry, encode


def main():
    renderer, registry = Renderer(), Registry.load()
    out = ROOT / "output" / "character_framing"
    out.mkdir(parents=True, exist_ok=True)
    codes = ["AEGIS", "FUKA", "JUNPEI", "JOKER", "PANTHER", "MONA", "CLOSER", "MONT", "LEON", "CATTLE"]
    results = [PullResult(registry.items["char:"+code], registry.items["char:"+code].rarity,
                          False, i+1, 0, 0) for i, code in enumerate(codes)]
    (out / "ten.jpg").write_bytes(encode(renderer.render_ten(results), quality=95))
    sheet = Image.new("RGB", (1600, 860), (25, 25, 30))
    for i, result in enumerate(results):
        tile = Image.new("RGBA", (320, 430), (25, 25, 30, 255))
        geo = CardGeometry(((150, 10), (230, 10), (150, 395), (70, 395)), 80, 385)
        foundation, pos = renderer._foundation_card(geo, 1, i, result.rarity, result.item.element, result.item.kind)
        tile.alpha_composite(foundation, pos)
        art, pos = renderer.art_layer(result, geo, 1, i)
        content = Image.new("RGBA", tile.size)
        content.alpha_composite(art, pos)
        mask = Image.new("L", tile.size)
        ImageDraw.Draw(mask).polygon(geo.quad, fill=255)
        tile.alpha_composite(Image.composite(content, Image.new("RGBA", tile.size), mask))
        ImageDraw.Draw(tile).text((20, 405), result.item.name, font=renderer.font(17), fill="white")
        sheet.paste(tile.convert("RGB"), (i%5*320, i//5*430))
    sheet.save(out / "characters.jpg", quality=95)
    for result in results[:3]:
        (out / (result.item.id.split(":")[1]+"-single.jpg")).write_bytes(
            encode(renderer.render_single(result), quality=95))
    print(out)


if __name__ == "__main__":
    main()
