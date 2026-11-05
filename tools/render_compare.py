"""把渲染结果与游戏参考截图并排输出，供人工目检。

    python tools/render_compare.py                       # 用 output/demo_ten.jpg 对比
    python tools/render_compare.py output/custom.jpg     # 指定自己的出图

读取 ``tools/fixtures/gacha_reference.jpg``（游戏内十连结果页），把本插件出图按
同一宽度缩放后上下拼接，写到 ``output/compare_reference.png``。
目标图本身是压缩 JPEG、且用的是官方立绘而非本项目素材，因此这里只做并排对照，
不设像素级阈值。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "tools" / "fixtures" / "gacha_reference.jpg"
OUT = ROOT / "output"


def _label_font(size: int):
    for candidate in (r"C:\Windows\Fonts\msyhbd.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def build_compare(target: Image.Image, reference: Image.Image, label: str = "current") -> Image.Image:
    width = 1280
    gap = 14
    ref = reference.convert("RGB")
    ref = ref.resize((width, round(ref.height * width / ref.width)), Image.Resampling.LANCZOS)
    shot = target.convert("RGB")
    shot = shot.resize((width, round(shot.height * width / shot.width)), Image.Resampling.LANCZOS)
    head = 34
    canvas = Image.new("RGB", (width, head * 2 + ref.height + shot.height + gap), (18, 18, 20))
    draw = ImageDraw.Draw(canvas)
    font = _label_font(20)
    draw.text((10, 7), "REFERENCE  game screenshot (target)", font=font, fill=(120, 200, 255))
    canvas.paste(ref, (0, head))
    y = head + ref.height + gap
    draw.text((10, y + 7), f"RENDER  {label}", font=font, fill=(255, 210, 90))
    canvas.paste(shot, (0, y + head))
    return canvas


def main(argv: list[str]) -> int:
    if not REFERENCE.exists():
        print(f"missing reference: {REFERENCE}")
        return 1
    target_path = Path(argv[1]) if len(argv) > 1 else OUT / "demo_ten.jpg"
    if not target_path.exists():
        print(f"missing render: {target_path} (run tools/render_demo.py first)")
        return 1
    reference = Image.open(REFERENCE)
    target = Image.open(target_path)
    result = build_compare(target, reference, label=target_path.name)
    OUT.mkdir(exist_ok=True)
    out_path = OUT / "compare_reference.png"
    result.save(out_path)
    print(f"compare -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
