"""逐物品输出实际卡槽裁切后的联系表，方便检查脸部、重心和大小。"""
from pathlib import Path
import sys
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.registry import Registry
from src.core.mechanics import PullResult
from src.render.renderer import Renderer, CardGeometry, foundation_geometry


def generate(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    renderer = Renderer()
    registry = Registry.load()
    for kind, kinds in (("characters", {"char", "character"}), ("personas", {"persona"})):
        items = [item for item in registry.items.values() if item.kind in kinds]
        for page in range((len(items) + 11) // 12):
            sheet = Image.new("RGB", (2040, 1800), (24, 25, 31))
            for index, item in enumerate(items[page * 12:(page + 1) * 12]):
                tile = Image.new("RGBA", (340, 900), (24, 25, 31, 255))
                actual = foundation_geometry(4, item.rarity)
                min_x = min(x for x,y in actual.quad)
                geo = CardGeometry(tuple((x-min_x+20,y-actual.top+20) for x,y in actual.quad),actual.width,actual.height)
                foundation, offset = renderer._foundation_card(geo, 1, index, item.rarity, item.element, item.kind)
                tile.alpha_composite(foundation, offset)
                result = PullResult(item, item.rarity, False, 1, 0, 0)
                layer = renderer.art_layer(result, geo, 1, index)
                if layer:
                    art, offset = layer
                    content = Image.new("RGBA", tile.size)
                    content.alpha_composite(art, offset)
                    mask = Image.new("L", tile.size)
                    ImageDraw.Draw(mask).polygon(geo.quad, fill=255)
                    tile.alpha_composite(Image.composite(content, Image.new("RGBA", tile.size), mask))
                draw = ImageDraw.Draw(tile)
                draw.text((5, 820), item.name, font=renderer.font(18), fill="white")
                draw.text((5, 846), item.id, font=renderer.font(12), fill=(160, 174, 210))
                if not layer or (item.kind in kinds and renderer.portrait(item) is None and not renderer._character_pair(item)):
                    draw.text((5, 870), "缺少素材 / 占位", font=renderer.font(16), fill=(255, 140, 120))
                sheet.paste(tile.convert("RGB"), (index % 6 * 340, index // 6 * 900))
            sheet.save(out / f"{kind}_{page+1:02}.jpg", quality=90)
        print(kind, len(items))


if __name__ == "__main__":
    generate(sys.argv[1] if len(sys.argv) > 1 else ROOT / "output" / "placements")
