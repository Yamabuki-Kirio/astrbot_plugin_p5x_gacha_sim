"""Side-by-side original and compressed portraits on a neutral background."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
names = ["lihui-guaidao-JandC", "lihui-guaidao-joker", "lihui-guaidao-marian", "lihui-guaidao-cattle"]
sheet = Image.new("RGB", (1200, 1440), "#777777")
draw = ImageDraw.Draw(sheet)
for index, name in enumerate(names):
    relative = Path("assets/character_layers/prepared") / name
    original = ROOT / "output/original-runtime-png" / relative.with_suffix(".png")
    compressed = ROOT / relative.with_suffix(".webp")
    a = Image.open(original).convert("RGBA")
    b = Image.open(compressed).convert("RGBA")
    print(name, "RGB mean absolute error", ImageStat.Stat(ImageChops.difference(a,b), a.getchannel("A")).mean[:3])
    for col, image in enumerate((a,b)):
        image.thumbnail((285,660), Image.Resampling.LANCZOS)
        x, y = (index % 2)*600+col*300, (index//2)*720
        draw.text((x+5,y+5), name, fill="white")
        draw.text((x+5,y+22), "PNG original" if col == 0 else "WebP Q95", fill="white")
        sheet.paste(image, (x+(300-image.width)//2,y+45), image)
sheet.save(ROOT / "output/webp-quality-review.jpg", quality=95)
