"""输出全部立绘的色带定位总览，用于人工检查裁切。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from src.core.registry import Registry
from src.core.mechanics import PullResult
from src.render.renderer import Renderer, CardGeometry


def main():
    registry, renderer = Registry.load(), Renderer()
    out = Path(__file__).resolve().parents[1] / "output" / "asset_review"
    out.mkdir(parents=True, exist_ok=True)
    for kind in ("char", "character", "persona", "weapon"):
        items = [item for item in registry.items.values()
                 if item.kind == kind and renderer.portrait(item) is not None]
        for start in range(0, len(items), 24):
            page = Image.new("RGB", (1200, 1320), (15, 16, 22))
            for slot, item in enumerate(items[start:start+24]):
                tile = Image.new("RGBA", (200, 300), (15, 16, 22, 255))
                geo = CardGeometry(((45, 12), (185, 12), (150, 270), (10, 270)), 140, 258)
                base, pos = renderer._foundation_card(geo, 1, slot, item.rarity, item.element)
                tile.alpha_composite(base, pos)
                result = PullResult(item, item.rarity, False, 1, 0, 0)
                layer = renderer.art_layer(result, geo, 1, slot)
                if layer:
                    art, pos = layer
                    mask = Image.new("L", tile.size)
                    ImageDraw.Draw(mask).polygon(geo.quad, fill=255)
                    content = Image.new("RGBA", tile.size)
                    content.alpha_composite(art, pos)
                    tile.alpha_composite(Image.composite(content, Image.new("RGBA", tile.size), mask))
                ImageDraw.Draw(tile).text((8, 280), item.name, font=renderer.font(12), fill="white")
                page.paste(tile.convert("RGB"), ((slot % 6)*200, (slot//6)*330))
            page.save(out / f"{kind}-{start//24+1:02d}.jpg", quality=90)
    print(out)


if __name__ == "__main__":
    main()
