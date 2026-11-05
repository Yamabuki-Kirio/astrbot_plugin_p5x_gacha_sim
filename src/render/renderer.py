"""P5X 风格抽卡结果渲染。"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..core.mechanics import PullResult
from ..core.models import Banner, Item

RARITY_COLORS = {
    5: ((250, 220, 82), (93, 36, 124)),
    4: ((255, 221, 59), (118, 79, 6)),
    3: ((67, 177, 255), (15, 65, 126)),
    2: ((89, 196, 133), (17, 75, 51)),
}
TEXT = (248, 248, 244)
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]


def _find_font(custom: str | None = None) -> str | None:
    for candidate in ([custom] if custom else []) + FONT_CANDIDATES:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


class Renderer:
    def __init__(self, assets_dir: Path | str | None = None, font_path: str | None = None):
        self.assets = Path(assets_dir) if assets_dir else Path(__file__).resolve().parents[2] / "assets"
        self.font_file = _find_font(font_path)
        self._font_cache: dict[int, ImageFont.FreeTypeFont] = {}
        self._portrait_cache: dict[str, Image.Image | None] = {}
        index_path = self.assets.parent / "data" / "asset_index.json"
        self.asset_index = (
            json.loads(index_path.read_text(encoding="utf-8")).get("items") or {}
            if index_path.exists()
            else {}
        )

    def font(self, size: int):
        if size not in self._font_cache:
            self._font_cache[size] = (
                ImageFont.truetype(self.font_file, size) if self.font_file else ImageFont.load_default(size)
            )
        return self._font_cache[size]

    def portrait(self, item: Item) -> Image.Image | None:
        if item.id in self._portrait_cache:
            return self._portrait_cache[item.id]
        relative = self.asset_index.get(item.id)
        image = None
        if relative:
            try:
                image = Image.open(self.assets / relative).convert("RGBA")
            except OSError:
                image = None
        self._portrait_cache[item.id] = image
        return image

    def _background(self, size: tuple[int, int]) -> Image.Image:
        path = self.assets / "p5x-gacha-background-v1.png"
        if path.exists():
            return Image.open(path).convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        return Image.new("RGBA", size, (5, 6, 9, 255))

    @staticmethod
    def _quad_mask(size: tuple[int, int], lean: int = 30) -> Image.Image:
        width, height = size
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).polygon([(lean, 0), (width, 0), (width - lean, height), (0, height)], fill=255)
        return mask

    def _result_card(self, result: PullResult, size: tuple[int, int], lean: int = 30) -> Image.Image:
        width, height = size
        light, dark = RARITY_COLORS[result.rarity]
        mask = self._quad_mask(size, lean)
        card = Image.new("RGBA", size, (*dark, 255))
        draw = ImageDraw.Draw(card)
        for y in range(height):
            mix = y / max(1, height - 1)
            color = tuple(int(light[i] * (1 - mix) + dark[i] * mix) for i in range(3))
            draw.line((0, y, width, y), fill=(*color, 255))
        sheen = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(sheen).polygon(
            [(width * 0.1, 0), (width, 0), (width * 0.72, height), (0, height)],
            fill=(255, 255, 255, 22),
        )
        card.alpha_composite(sheen)

        art = self.portrait(result.item)
        art_bottom = height
        if art is not None and result.rarity < 5:
            # 素材常带较宽透明画布；按可见像素裁切后再适配卡面。
            alpha_box = art.getchannel("A").getbbox()
            if alpha_box:
                art = art.crop(alpha_box)
            # P5X 结果页的人物不是缩在卡片中央，而是以接近满高的海报方式铺在色带上。
            target_height = height * 0.96
            scale = target_height / art.height
            resized = art.resize(
                (max(1, int(art.width * scale)), max(1, int(art.height * scale))),
                Image.Resampling.LANCZOS,
            )
            x = (width - resized.width) // 2
            y = art_bottom - resized.height
            card.alpha_composite(resized, (x, y))
        elif art is None:
            # 低星人格面具暂无素材，明确使用剪影，不用错误角色图冒充。
            draw.ellipse((width * 0.23, height * 0.20, width * 0.77, height * 0.64), fill=(8, 10, 17, 150))
            draw.polygon(
                [(width * 0.16, height * 0.69), (width * 0.84, height * 0.69),
                 (width * 0.68, height * 0.35), (width * 0.32, height * 0.35)],
                fill=(8, 10, 17, 150),
            )

        if result.is_up:
            draw.polygon([(width - 68, 0), (width, 0), (width, 66)], fill=(224, 24, 58, 235))
            draw.text((width - 25, 21), "UP", font=self.font(16), fill="white", anchor="mm")

        card.putalpha(mask)
        return card

    def render_ten(
        self,
        results: Sequence[PullResult],
        banner: Banner | None = None,
        user_name: str = "",
        footer: str = "",
    ) -> Image.Image:
        width, height = 1920, 905
        canvas = self._background((width, height))
        count = max(1, len(results))
        # 宽窄、高低和倾角刻意不齐，接近游戏结果页的海报拼贴节奏。
        rhythm = [
            (196, 618, 31, 8), (205, 650, 38, 18), (190, 632, 28, 2),
            (214, 668, 44, 14), (198, 646, 34, 5), (208, 660, 42, 20),
            (194, 625, 29, 7), (216, 675, 46, 16), (198, 640, 35, 3),
            (210, 656, 40, 12),
        ]
        widths = []
        for i, result in enumerate(results):
            base_w = rhythm[i % len(rhythm)][0]
            widths.append(base_w + (54 if result.rarity >= 5 else 20 if result.rarity == 4 else 0))
        overlaps = [50 + (8 if results[i].rarity >= 5 or results[i + 1].rarity >= 5 else 0)
                    for i in range(max(0, count - 1))]
        total_w = sum(widths) - sum(overlaps)
        start_x = (width - total_w) // 2
        positions = []
        cursor = start_x
        for i in range(count):
            positions.append(cursor)
            if i < count - 1:
                cursor += widths[i] - overlaps[i]
        # 低稀有度先画，高稀有度最后画；序号横向位置仍是真实抽取顺序。
        order = sorted(range(count), key=lambda i: (results[i].rarity, i))
        for index in order:
            result = results[index]
            base_w, base_h, lean, y_shift = rhythm[index % len(rhythm)]
            card_w = widths[index]
            card_h = base_h + (118 if result.rarity >= 5 else 42 if result.rarity == 4 else 0)
            x = positions[index]
            y = 128 + y_shift - (88 if result.rarity >= 5 else 25 if result.rarity == 4 else 0)
            card = self._result_card(result, (card_w, card_h), lean + (8 if result.rarity >= 5 else 0))
            if result.rarity >= 5:
                glow = Image.new("RGBA", (card_w + 70, card_h + 70), (0, 0, 0, 0))
                glow_mask = self._quad_mask((card_w + 36, card_h + 36), lean + 10)
                glow.paste((183, 91, 255, 225), (17, 17), glow_mask)
                glow = glow.filter(ImageFilter.GaussianBlur(22))
                canvas.alpha_composite(glow, (x - 35, y - 35))
            canvas.alpha_composite(card, (x, y))
            if result.rarity >= 5:
                # 高稀有度立绘脱离色带裁切，完整前凸并覆盖相邻结果。
                art = self.portrait(result.item)
                if art is not None:
                    alpha_box = art.getchannel("A").getbbox()
                    if alpha_box:
                        art = art.crop(alpha_box)
                    scale = card_h * 0.91 / art.height
                    art = art.resize(
                        (max(1, int(art.width * scale)), max(1, int(art.height * scale))),
                        Image.Resampling.LANCZOS,
                    )
                    canvas.alpha_composite(
                        art,
                        (x + (card_w - art.width) // 2, y + card_h - art.height),
                    )
        return canvas.convert("RGB")

    def render_single(
        self,
        result: PullResult,
        banner: Banner | None = None,
        user_name: str = "",
        footer: str = "",
    ) -> Image.Image:
        canvas = self._background((1200, 905))
        card = self._result_card(result, (360, 760), 48)
        canvas.alpha_composite(card, ((1200 - 360) // 2, 72))
        return canvas.convert("RGB")


def encode(image: Image.Image, quality: int = 90) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
