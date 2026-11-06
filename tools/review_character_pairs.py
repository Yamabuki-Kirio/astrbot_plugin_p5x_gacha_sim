"""生成两个用户目录的角色素材对照表。"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCES = [Path(r"C:\Users\Administrator\Downloads\Texture2D-20261106T125440Z-1-001\Texture2D"),
           Path(r"C:\Users\Administrator\Downloads\Sprite-20261106T134141Z-1-001\Sprite")]

if __name__ == "__main__":
    files = {p.name: p for folder in SOURCES for p in folder.glob("*.png")}
    candidates = [p for name, p in sorted(files.items())
                  if not name.startswith("lihui-guaidao-") or
                  any(code in name for code in ("doctor", "tembin", "kii", "seiji", "closerS", "montManwu", "luceYY", "kotomo"))]
    out = ROOT / "output" / "character_review"
    out.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 13)
    from src.core.registry import Registry
    from src.render.renderer import Renderer
    renderer = Renderer()
    chars = [i for i in Registry.load().items.values() if i.kind in ("char", "character")
             and not renderer._character_pair(i)]
    sheet = Image.new("RGB", (1500, 1500), (38,38,42))
    draw = ImageDraw.Draw(sheet)
    for index, item in enumerate(chars):
        x,y = index%6*250,index//6*250
        image = renderer.portrait(item)
        if image:
            image = image.copy()
            image.thumbnail((240,215))
            sheet.paste(image,(x+(250-image.width)//2,y),image)
        draw.text((x+3,y+220),item.id,font=font,fill="white")
    sheet.save(out / "unmatched.jpg",quality=92)
    for page in range((len(candidates)+35)//36):
        sheet = Image.new("RGB", (1500, 1500), (38, 38, 42))
        draw = ImageDraw.Draw(sheet)
        for index, path in enumerate(candidates[page*36:(page+1)*36]):
            x, y = index%6*250, index//6*250
            with Image.open(path) as source:
                image = source.convert("RGBA")
            bounds = image.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
            if bounds:
                image = image.crop(bounds)
            image.thumbnail((240, 215))
            sheet.paste(image, (x+(250-image.width)//2, y), image)
            draw.text((x+3,y+216), path.name[:34], font=font, fill="white")
            draw.text((x+3,y+232), path.name[34:], font=font, fill="white")
        sheet.save(out / f"sheet_{page}.jpg", quality=92)
        print(out / f"sheet_{page}.jpg")
