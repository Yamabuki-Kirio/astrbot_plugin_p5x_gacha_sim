"""P5X 风格抽卡结果渲染。

布局按游戏内十连结果页（1920×905 设计稿）还原：

* 10 条倾斜的四边形色带，统一倾角、高低错落、互相遮压；
* 立绘以海报方式贴进色带并被裁切，只有 5★ 会整体前凸盖住相邻结果；
* 每条色带底部的图标、数量与稀有度强调（5★ 星芒 / 4★ 燃焰 / 3★ 闪电 / 2★ 尾焰）；
* 顶部资源栏、NEW 贴纸、相机与分享按钮。

参考：``tools/fixtures/gacha_reference.jpg``，可用 ``tools/render_compare.py`` 并排对照。
"""

from __future__ import annotations

import io
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from ..core.mechanics import PullResult
from ..core.models import Banner, Item

DESIGN_W, DESIGN_H = 1920, 873

# ---------------------------------------------------------------------------
# 稀有度视觉
# ---------------------------------------------------------------------------
# light/dark 用于色带竖向渐变；flat 是低星（2★/3★）的平涂主色。
RARITY_STYLE: dict[int, dict] = {
    5: {
        # 参考实测：5★ 色带是深蓝底（区域均值 ≈ (85,96,142)），金色只用于边框与奖励。
        "light": (66, 76, 190), "dark": (14, 18, 74), "flat": (40, 48, 140),
        "edge": (255, 246, 206), "frame": (255, 236, 150), "frame_inner": (150, 92, 14),
        "flare": (255, 244, 190), "glow": (170, 92, 255), "shield": 1.0,
        "reward": 30,
    },
    4: {
        "light": (255, 196, 66), "dark": (138, 84, 6), "flat": (188, 126, 18),
        "edge": (255, 250, 210), "frame": (255, 214, 110), "frame_inner": (120, 68, 4),
        "flare": (255, 206, 78), "glow": (255, 196, 90), "shield": 0.8,
        "reward": 15,
    },
    3: {
        # 参考里没有亮色 3★：默认深金，奇数位换成暗绿，避免两条 3★ 撞色。
        "light": (118, 104, 56), "dark": (44, 40, 20), "flat": (96, 86, 46),
        "edge": (255, 250, 236), "frame": (222, 206, 158), "frame_inner": (86, 74, 34),
        "flare": (255, 236, 190), "glow": (230, 190, 120), "shield": 0.7,
        "reward": 10,
    },
    2: {
        "light": (58, 158, 110), "dark": (10, 58, 38), "flat": (34, 126, 82),
        "edge": (255, 255, 255), "frame": (208, 246, 220), "frame_inner": (10, 62, 38),
        "flare": (150, 255, 176), "glow": (90, 210, 150), "shield": 0.62,
        "reward": 5,
    },
}

# 3★ 的第二个配色档（暗绿），供相邻 3★ 交替使用。
RARITY_ALT_STYLE: dict[int, dict] = {
    3: {
        "light": (58, 122, 86), "dark": (16, 52, 36), "flat": (40, 92, 64),
        "edge": (230, 250, 238), "frame": (176, 226, 198), "frame_inner": (12, 48, 32),
        "flare": (196, 255, 220), "glow": (110, 210, 160), "shield": 0.7,
        "reward": 10,
    },
}


def style_for(rarity: int, slot: int = 0) -> dict:
    """按稀有度和序号取配色；3★ 在 slot 为奇数时用暗绿档。"""
    if rarity == 3 and slot % 2 == 1:
        return RARITY_ALT_STYLE[3]
    return RARITY_STYLE[rarity]
# 兼容旧名字：部分外部脚本会读这两张表。
RARITY_COLORS = {rarity: (style["light"], style["dark"]) for rarity, style in RARITY_STYLE.items()}
TEXT = (248, 248, 244)

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]
LATIN_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\ariblk.ttf",
    r"C:\Windows\Fonts\impact.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# ---------------------------------------------------------------------------
# 布局：来自参考截图（1280×582）按 1.5 倍换算到 1920×873，再下移到 905 高画布。
# x 为色带顶边左端，bottom 为色带底边位置（顶边右端 = x + slant）。
# ---------------------------------------------------------------------------
SLANT = 151
CARD_LAYOUT: tuple[tuple[int, int, int, int], ...] = (
    # (x, width, top, bottom) —— 顶边整体上提 20px，让画面上方留白更接近截图
    (58, 300, 120, 632),
    (268, 292, 120, 632),
    (470, 285, 100, 596),
    (664, 288, 100, 596),
    (858, 288, 88, 582),
    (1052, 290, 88, 582),
    (1246, 288, 100, 596),
    (1440, 292, 100, 596),
    (1634, 288, 76, 570),
    (1810, 250, 94, 570),
)
# 5★ 的前凸量（相对自身色带，按比例）
FIVE_STAR_BOOST = {"width": 1.06, "height": 1.06, "dx": -0.03, "top": 16}
# 每条色带的轻微抖动，保证十连结果高低错落；种子固定，出图稳定。
JITTER = ((0, -6), (4, 14), (-6, -2), (7, 9), (-3, 4), (5, -8), (-5, 6), (3, -4), (-2, 10), (6, 2))


@dataclass(frozen=True)
class CardGeometry:
    """一条色带的四边形顶点（上左、上右、下右、下左）。"""

    quad: tuple[tuple[float, float], ...]
    width: float
    height: float

    @property
    def top(self) -> float:
        return self.quad[0][1]


def card_geometry(index: int, rarity: int, window: int | None = None) -> CardGeometry:
    """按序号与稀有度计算色带四边形；5★ 额外加宽加高形成前凸。

    ``window`` 是这一批的实际张数（十连=10）。只有 10 张时用整张布局表，
    否则取以 ``index`` 为中心的一段，保证单抽/少于十张时画面居中。
    """
    table = CARD_LAYOUT
    if window is not None and window < len(table):
        span = max(1, window)
        start = max(0, min(len(table) - span, index - span // 2))
        table = CARD_LAYOUT[start:start + span]
        index = index - start
    x, width, top, bottom = table[index % len(table)]
    dx, dy = JITTER[index % len(JITTER)]
    top += dy
    bottom += dy
    slant = SLANT
    if rarity >= 5:
        boost = FIVE_STAR_BOOST
        width = width * boost["width"]
        height = (bottom - top) * boost["height"]
        top -= boost["top"]
        bottom = top + height
        x += width * boost["dx"]
    else:
        x += dx
    bottom_x = x + slant
    return CardGeometry(
        quad=(
            (float(x), float(top)),
            (float(x + width), float(top)),
            (float(bottom_x + width), float(bottom)),
            (float(bottom_x), float(bottom)),
        ),
        width=width,
        height=bottom - top,
    )


def _polygon(quad: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(round(px, 2), round(py, 2)) for px, py in quad]


def _inner_quad(quad: Sequence[tuple[float, float]], inset: float) -> list[tuple[float, float]]:
    """把四边形向内收缩：竖边水平内移、横边垂直内移。"""
    (tlx, tly), (trx, _), (brx, bry), (blx, _) = quad
    cx = (tlx + trx + brx + blx) / 4
    cy = (tly + bry) / 2
    result = []
    for px, py in quad:
        dx = (cx - px)
        result.append((px + math.copysign(min(abs(dx), inset), dx), py + (inset if py < cy else -inset)))
    return _polygon(result)


def _offset_quad(quad: Sequence[tuple[float, float]], dx: float, dy: float) -> list[tuple[float, float]]:
    return _polygon([(px + dx, py + dy) for px, py in quad])


class Renderer:
    def __init__(self, assets_dir: Path | str | None = None, font_path: str | None = None):
        self.assets = Path(assets_dir) if assets_dir else Path(__file__).resolve().parents[2] / "assets"
        self.font_file = _find_font(font_path)
        self.latin_font_file = _find_font(None, LATIN_FONT_CANDIDATES)
        self._font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
        self._portrait_cache: dict[str, Image.Image | None] = {}
        self._background_cache: dict[tuple[int, int], Image.Image] = {}
        index_path = self.assets.parent / "data" / "asset_index.json"
        self.asset_index = (
            json.loads(index_path.read_text(encoding="utf-8")).get("items") or {}
            if index_path.exists()
            else {}
        )

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------
    def font(self, size: int, latin: bool = False):
        key = ("latin" if latin else "cjk", size)
        if key not in self._font_cache:
            path = (self.latin_font_file if latin else self.font_file) or self.font_file
            self._font_cache[key] = (
                ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
            )
        return self._font_cache[key]

    def portrait(self, item: Item) -> Image.Image | None:
        if item.id in self._portrait_cache:
            return self._portrait_cache[item.id]
        relative = self.asset_index.get(item.id)
        image = None
        if relative:
            try:
                image = Image.open(self.assets / relative).convert("RGBA")
                box = image.getchannel("A").getbbox()
                if box:
                    image = image.crop(box)
            except (OSError, ValueError):
                image = None
        self._portrait_cache[item.id] = image
        return image

    def _background(self, size: tuple[int, int]) -> Image.Image:
        if size in self._background_cache:
            return self._background_cache[size].copy()
        path = self.assets / "p5x-gacha-background-v1.png"
        if path.exists():
            with Image.open(path) as source:
                canvas = source.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        else:
            canvas = Image.new("RGBA", size, (5, 6, 9, 255))
        self._background_cache[size] = canvas
        return canvas.copy()

    @staticmethod
    def _scale(size: tuple[int, int]) -> float:
        return size[0] / DESIGN_W

    # ------------------------------------------------------------------
    # 色带
    # ------------------------------------------------------------------
    def _card_canvas(self, geometry: CardGeometry, scale: float) -> tuple[Image.Image, tuple[int, int]]:
        pad = int(48 * scale) + 8
        xs = [p[0] for p in geometry.quad]
        ys = [p[1] for p in geometry.quad]
        box = (math.floor(min(xs)) - pad, math.floor(min(ys)) - pad,
               math.ceil(max(xs)) + pad, math.ceil(max(ys)) + pad)
        size = (box[2] - box[0], box[3] - box[1])
        return Image.new("RGBA", size, (0, 0, 0, 0)), (box[0], box[1])

    @staticmethod
    def _fill_gradient(canvas: Image.Image, quad: Sequence[tuple[float, float]], light, dark,
                       slope: bool = True, alpha: int = 255) -> None:
        tly = quad[0][1]
        bry = quad[3][1]
        mask = Image.new("L", canvas.size, 0)
        ImageDraw.Draw(mask).polygon(_polygon(quad), fill=255)
        width, height = canvas.size
        top_color = light
        bottom_color = dark
        out_alpha = max(0, min(255, alpha))
        fill = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(fill)
        span = max(1.0, bry - tly)
        step = 2
        for y in range(0, height, step):
            mix = min(1.0, max(0.0, (y - tly) / span))
            color = tuple(int(top_color[i] * (1 - mix) + bottom_color[i] * mix) for i in range(3))
            draw.rectangle((0, y, width, y + step), fill=(*color, out_alpha))
        if slope:
            # 左上角更亮、右下角更暗的对角线明暗，接近游戏里斜切的光照。
            shade = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(shade)
            sdraw.polygon([(0, 0), (width, 0), (width, height)], fill=(255, 255, 255, 26))
            shade = shade.filter(ImageFilter.GaussianBlur(max(2, width // 16)))
            fill = Image.alpha_composite(fill, Image.composite(shade, Image.new("RGBA", fill.size, (0, 0, 0, 0)), mask))
        canvas.paste(fill, (0, 0), mask)

    def _card_base(self, rarity: int, canvas: Image.Image, quad_local: Sequence[tuple[float, float]],
                   scale: float, alpha: int = 255, slot: int = 0) -> None:
        style = style_for(rarity, slot)
        self._fill_gradient(canvas, quad_local, style["light"], style["dark"], alpha=alpha)
        if rarity <= 3:
            # 低星是平涂：上面压一层主色，保留一点顶端高光。
            flat = Image.new("RGBA", canvas.size, (*style["flat"], min(205, alpha)))
            mask = Image.new("L", canvas.size, 0)
            ImageDraw.Draw(mask).polygon(_polygon(quad_local), fill=255)
            canvas.alpha_composite(Image.composite(flat, Image.new("RGBA", canvas.size, (0, 0, 0, 0)), mask))

    def _frame(self, canvas: Image.Image, quad_local: Sequence[tuple[float, float]], rarity: int,
               scale: float, slot: int = 0) -> None:
        """高星双线内描边，低星单线粗描边。"""
        style = style_for(rarity, slot)
        draw = ImageDraw.Draw(canvas)
        width = max(2, int(5 * scale))
        draw.line(_polygon(quad_local) + [_polygon(quad_local)[0]], fill=(*style["frame"], 255), width=width, joint="curve")
        if rarity >= 4:
            inner = _inner_quad(quad_local, max(5, 9 * scale))
            draw.line(inner + [inner[0]], fill=(*style["frame_inner"], 235), width=max(2, int(2.4 * scale)), joint="curve")
        if rarity >= 5:
            # 5★ 外发光
            glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).line(_polygon(quad_local) + [_polygon(quad_local)[0]],
                                      fill=(*style["glow"], 200), width=max(3, int(7 * scale)), joint="curve")
            canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(2, int(6 * scale)))))

    # ------------------------------------------------------------------
    # 立绘
    # ------------------------------------------------------------------
    def _place_art(self, card: Image.Image, item: Item, geometry: CardGeometry, rarity: int,
                   local_quad: Sequence[tuple[float, float]], scale: float, slot: int = 0) -> None:
        """把立绘/剪影贴上卡片；立绘超出色带的部分会被裁掉（5★ 除外由外层处理）。"""
        art = self.portrait(item)
        height = int(geometry.height)
        width = int(geometry.width)
        mask = Image.new("L", card.size, 0)
        ImageDraw.Draw(mask).polygon(_polygon(local_quad), fill=255)

        if art is None:
            silhouette = self._silhouette(width, height, rarity, scale, slot=slot)
            layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
            # 人格面具的剪影居中贴在中部，底部给日后的奖励图标留空间。
            layer.paste(silhouette, (int((card.width - silhouette.width) / 2),
                                     int(local_quad[3][1] - height * 0.20 - silhouette.height)), silhouette)
            card.alpha_composite(Image.composite(layer, Image.new("RGBA", card.size, (0, 0, 0, 0)), mask))
            return

        # 角色以身高为准铺满色带；武器按原比例缩到色带内，避免枪管被切掉。
        if item.kind == "character":
            factor = height * (1.02 if rarity >= 5 else 0.98) / art.height
        else:
            factor = min(width * 0.78 / art.width, height * (0.72 if rarity >= 5 else 0.66) / art.height)
        resized = art.resize((max(1, int(art.width * factor)), max(1, int(art.height * factor))),
                             Image.Resampling.LANCZOS)
        x = int((card.width - resized.width) / 2)
        bottom = local_quad[3][1] if item.kind == "character" else local_quad[3][1] - height * 0.06
        y = int(bottom - resized.height)
        layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
        layer.paste(resized, (x, y), resized)
        card.alpha_composite(Image.composite(layer, Image.new("RGBA", card.size, (0, 0, 0, 0)), mask))

    def _five_backdrop(self, canvas: Image.Image, geometry: CardGeometry, scale: float) -> None:
        """5★ 后方的那团巨大蓝色身影：截图里被前凸立绘挡住大半，仍能读出「人形 + 红眼」。"""
        (tlx, tly), (trx, _), (brx, bry), (blx, _) = geometry.quad
        cx = (tlx + trx + brx + blx) / 4
        width = geometry.width
        height = geometry.height
        # 直接铺满色带：宽 = 色带宽度，高 = 色带高度，避免又被自己的卡片盖回去。
        silhouette = self._silhouette(int(width * 1.02), int(height * 1.08), 5, scale, palette="blue",
                                      fill=True)
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        layer.paste(silhouette, (int(cx - silhouette.width / 2), int(bry + 10 * scale - silhouette.height)),
                    silhouette)
        # 直接叠上去：不透明蓝影才压得住背景纹理（参考里也是实心的靛蓝团）。
        canvas.alpha_composite(layer)
        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((cx - width * 0.85, bry - height * 0.45, cx + width * 0.85, bry + height * 0.12),
                                     fill=(72, 46, 170, 130))
        canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(int(26 * scale))))

    def _silhouette(self, width: int, height: int, rarity: int, scale: float, palette: str = "dark",
                    fill: bool = False, slot: int = 0) -> Image.Image:
        """剪影：暗色长袍 + 头 + 角；``palette="blue"`` 时是 5★ 背后那团蓝色身影。"""
        if palette == "blue":
            # 蓝影要撑满整条色带：头在上部，肩膀展开到接近全宽。
            return self._monster_silhouette(width, height, scale)
        style = style_for(rarity, slot)
        w = int(width * (1.0 if fill else 0.66))
        h = int(height * (1.0 if fill else 0.60))
        image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        body = (8, 10, 18, 178)
        rim = (*style["frame"], 78)
        eye = (*style["flare"], 150)
        edge = max(2, int(3 * scale))
        cx = w * 0.5
        head_r = w * 0.22
        head_cx, head_cy = cx, h * 0.20
        # 角
        for sign in (-1, 1):
            draw.polygon([(head_cx + sign * head_r * 0.55, head_cy - head_r * 0.55),
                          (head_cx + sign * head_r * 0.15, head_cy - head_r * 1.75),
                          (head_cx + sign * head_r * 0.95, head_cy - head_r * 0.25)],
                         fill=body, outline=rim)
        draw.ellipse((head_cx - head_r, head_cy - head_r * 0.9,
                      head_cx + head_r, head_cy + head_r * 0.9), fill=body, outline=rim, width=edge)
        # 长袍：下摆张开、肩部收窄
        draw.polygon([
            (cx - w * 0.44, h * 1.0), (cx + w * 0.44, h * 1.0),
            (cx + w * 0.30, h * 0.56), (cx + w * 0.13, h * 0.36),
            (cx - w * 0.13, h * 0.36), (cx - w * 0.30, h * 0.56),
        ], fill=body, outline=rim)
        # 两点眼部亮斑：普通剪影用稀薄的高光。
        for sign in (-1, 1):
            draw.ellipse((head_cx + sign * head_r * 0.38 - head_r * 0.12, head_cy - head_r * 0.12,
                          head_cx + sign * head_r * 0.38 + head_r * 0.12, head_cy + head_r * 0.12),
                         fill=eye)
        return image

    @staticmethod
    def _monster_silhouette(width: int, height: int, scale: float) -> Image.Image:
        """5★ 背后的巨大蓝色身影。

        参考里它是一团**混沌的蓝色雾气**而不是清晰人形：用斜片 + 水平条纹遮罩把轮廓
        打散，只留上半部的红眼可辨。头小、肩宽、下摆没入卡片底部。
        """
        w, h = max(2, int(width)), max(2, int(height))
        image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        bright = (74, 82, 236, 255)
        deep = (8, 10, 44, 255)
        eye = (255, 44, 40, 255)
        cx = w * 0.5
        head_r = min(w * 0.115, h * 0.052)
        head_cy = h * 0.14
        torso = [
            (cx - w * 0.46, h * 0.99), (cx + w * 0.46, h * 0.99),
            (cx + w * 0.44, h * 0.60), (cx + w * 0.30, h * 0.36),
            (cx + w * 0.14, h * 0.26), (cx - w * 0.14, h * 0.26),
            (cx - w * 0.30, h * 0.36), (cx - w * 0.44, h * 0.60),
        ]
        draw.polygon(torso, fill=bright)
        # 竖向明暗
        shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shade)
        for i in range(48):
            t = abs(i / 47 - 0.5) * 2
            band_w = w * 0.46 * (1 - t)
            sdraw.polygon([(cx - band_w, h * 0.26), (cx + band_w, h * 0.26),
                           (cx + band_w * 1.04, h * 0.99), (cx - band_w * 1.04, h * 0.99)],
                          fill=(*deep[:3], int(150 * t ** 1.5)))
        image.alpha_composite(shade)
        # 打散轮廓：斜片与水平条纹互相叠加，遮掉一部分，做出「雾气」的碎边。
        shatter = Image.new("L", (w, h), 255)
        sd = ImageDraw.Draw(shatter)
        band = max(3, int(h * 0.028))
        for y in range(int(h * 0.30), h, band * 2):
            sd.rectangle((0, y, w, y + band), fill=150)
        for k in range(5):
            x0 = w * (0.04 + k * 0.20)
            sd.polygon([(x0, h * 0.24), (x0 + w * 0.10, h * 0.24), (x0 + w * 0.22, h), (x0 + w * 0.12, h)],
                       fill=120)
        shatter = shatter.filter(ImageFilter.GaussianBlur(max(1, int(2 * scale))))
        image.putalpha(ImageChops.multiply(image.getchannel("A"), shatter))
        # 肩部辉光，强化「胸口发光」的观感。
        chest = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(chest).ellipse((cx - w * 0.28, h * 0.28, cx + w * 0.28, h * 0.62),
                                      fill=(120, 130, 255, 120))
        chest = chest.filter(ImageFilter.GaussianBlur(max(3, int(16 * scale))))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).polygon(torso, fill=255)
        image.alpha_composite(Image.composite(chest, Image.new("RGBA", (w, h), (0, 0, 0, 0)), mask))
        # 头部与红眼（最后画，不被光斑冲淡）
        draw = ImageDraw.Draw(image)
        draw.ellipse((cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r), fill=deep)
        for sign in (-1, 1):
            ex = cx + sign * head_r * 0.46
            draw.ellipse((ex - head_r * 0.24, head_cy - head_r * 0.20,
                          ex + head_r * 0.24, head_cy + head_r * 0.20), fill=eye)
        # 底部淡出，让卡片紫色光晕收边
        fade = Image.new("L", (w, h), 255)
        fdraw = ImageDraw.Draw(fade)
        for y in range(int(h * 0.74), h):
            t = (y - h * 0.74) / (h * 0.26)
            fdraw.line((0, y, w, y), fill=int(255 * (1 - t)))
        image.putalpha(ImageChops.multiply(image.getchannel("A"), fade))
        return image

    # ------------------------------------------------------------------
    # 底部奖励与强调
    # ------------------------------------------------------------------
    def _reward_icon(self, size: int) -> Image.Image:
        """奖励图标：左侧移动箭头 + 中央金色四角星 + 右侧小箭头，与截图的三件套一致。"""
        s = size
        w = int(s * 1.18)
        icon = Image.new("RGBA", (w, s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon)
        # 左箭头
        draw.polygon([(0, s * 0.30), (w * 0.20, s * 0.5), (0, s * 0.70)], fill=(255, 255, 255, 235))
        # 中央四角星
        star_cx, star_r = w * 0.47, s * 0.42
        draw.polygon([(star_cx, s * 0.5 - star_r), (star_cx + star_r * 0.34, s * 0.5 - star_r * 0.34),
                      (star_cx + star_r, s * 0.5), (star_cx + star_r * 0.34, s * 0.5 + star_r * 0.34),
                      (star_cx, s * 0.5 + star_r), (star_cx - star_r * 0.34, s * 0.5 + star_r * 0.34),
                      (star_cx - star_r, s * 0.5), (star_cx - star_r * 0.34, s * 0.5 - star_r * 0.34)],
                     fill=(255, 226, 120, 255), outline=(255, 250, 225, 255))
        # 右箭头
        draw.polygon([(w * 0.80, s * 0.30), (w, s * 0.5), (w * 0.80, s * 0.70)], fill=(255, 255, 255, 205))
        return icon

    def _reward_chip(self, canvas: Image.Image, quad_local: Sequence[tuple[float, float]], rarity: int,
                     scale: float, anchor_x: float | None = None, anchor_y: float | None = None,
                     size: float | None = None, count_dx: float | None = None,
                     count_dy: float = 0.0) -> None:
        """奖励图标 + 数量；位置默认贴色带底部，也可以由印章指定。"""
        style = RARITY_STYLE[rarity]
        blx, bly = quad_local[3]
        brx = quad_local[2][0]
        size = int(size if size is not None else (62 if rarity >= 5 else 56) * scale)
        cx = anchor_x if anchor_x is not None else (blx + brx) / 2
        cy = anchor_y if anchor_y is not None else bly - size * 0.62
        icon = self._reward_icon(size)
        draw = ImageDraw.Draw(canvas)
        for radius, alpha in ((size * 0.60, 200), (size * 0.76, 120)):
            draw.arc((cx - radius, cy - radius, cx + radius, cy + radius), 150, 30,
                     fill=(255, 214, 110, alpha), width=max(2, int(3 * scale)))
        canvas.alpha_composite(icon, (int(cx - size * 0.59), int(cy - size * 0.42)))
        count = str(style["reward"]) if rarity >= 4 else ""
        if count:
            font_size = int(size * 0.52)
            dx = count_dx if count_dx is not None else size * 0.46
            draw.text((cx + dx, cy + count_dy), count, font=self.font(font_size, latin=True),
                      fill=(255, 255, 255, 255), anchor="lm",
                      stroke_width=max(2, int(3 * scale)), stroke_fill=(0, 0, 0, 235))

    def _card_emblem(self, canvas: Image.Image, quad_local: Sequence[tuple[float, float]], rarity: int,
                     scale: float, slot: int, with_reward: bool = True, card_scale: float = 1.0) -> None:
        """色带底部的「印章」：圆底 + 稀有度徽记；5★/4★ 左侧同一水平行放奖励图标与数量。

        整行按照色带最宽处居中，并按卡宽/卡高自适应，保证相邻结果之间不会互相压住。
        """
        fit = max(0.62, min(1.0, card_scale, scale * 0.9)) if scale else 1.0

        def k(value: float) -> float:
            return value * scale * fit

        blx, bly = quad_local[3]
        brx = quad_local[2][0]
        width = abs(brx - blx)
        radius = k(36 if rarity >= 5 else 30)
        has_reward = rarity >= 4 and with_reward
        icon_size = k(40)
        count_w = icon_size * 0.58 if has_reward else 0.0
        gap = k(5)
        # 行宽 = 奖励图标 + 数字 + 间距 + 圆底；按色带宽度夹住后整体居中。
        row_w = min(icon_size * 0.86 + count_w + gap + radius * 2, width * 0.80) if has_reward else radius * 2
        row_w = max(row_w, radius * 2)
        left = (blx + brx) / 2 - row_w / 2
        cy = bly - radius * 1.16
        if has_reward:
            self._reward_chip(canvas, quad_local, rarity, fit * scale,
                              anchor_x=left + icon_size * 0.41, anchor_y=cy, size=icon_size,
                              count_dx=icon_size * 0.55, count_dy=0.0)
            cx = left + row_w - radius
        else:
            cx = left + radius
        style = style_for(rarity, slot)
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        base = tuple(int(style["dark"][i] * 0.55) for i in range(3))
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*base, 232))
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                     outline=(*style["frame"], 255), width=max(2, int(4 * scale * fit)))
        inner = radius * 0.46
        if rarity >= 5:
            draw.polygon([(cx, cy - inner * 1.5), (cx + inner, cy), (cx, cy + inner * 1.5),
                          (cx - inner, cy)], fill=(196, 150, 255, 250),
                         outline=(255, 255, 255, 245))
        elif rarity == 4:
            draw.polygon([(cx, cy - inner * 1.3), (cx + inner * 0.7, cy), (cx, cy + inner * 1.3),
                          (cx - inner * 0.7, cy)], fill=(*style["frame"], 245),
                         outline=(255, 255, 255, 220))
        else:
            # 低星按 slot 轮换 4 种徽记，避免每条都长得一样。
            self._low_star_mark(draw, cx, cy, inner, slot, style, max(2, int(4 * scale * fit)))
        canvas.alpha_composite(layer)

    @staticmethod
    def _low_star_mark(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, slot: int,
                       style: dict, width: int) -> None:
        face = (255, 255, 255, 235)
        tint = (*style["frame"], 215)
        kind = slot % 4
        if kind == 0:      # 双弧
            draw.arc((cx - r * 1.6, cy - r * 1.2, cx + r * 1.6, cy + r * 1.2), 200, 340, fill=face, width=width)
            draw.arc((cx - r * 0.9, cy - r * 0.4, cx + r * 2.1, cy + r * 1.4), 200, 340, fill=tint, width=width)
        elif kind == 1:    # 狐面轮廓
            draw.polygon([(cx - r * 1.5, cy - r * 0.6), (cx, cy + r * 1.4), (cx + r * 1.5, cy - r * 0.6),
                          (cx, cy - r * 1.2)], outline=face, width=width)
        elif kind == 2:    # 菱形
            draw.polygon([(cx, cy - r * 1.4), (cx + r * 1.1, cy), (cx, cy + r * 1.4), (cx - r * 1.1, cy)],
                         outline=face, width=width)
        else:              # 螺旋
            draw.arc((cx - r * 1.4, cy - r * 1.4, cx + r * 1.4, cy + r * 1.4), 20, 300, fill=face, width=width)
            draw.arc((cx - r * 0.7, cy - r * 0.7, cx + r * 0.7, cy + r * 0.7), 200, 480, fill=tint, width=width)

    def _accent(self, canvas: Image.Image, quad_local: Sequence[tuple[float, float]], rarity: int,
                scale: float, slot: int = 0) -> None:
        """在色带底部外侧画稀有度强调：5★ 星芒、4★ 燃焰、3★ 闪电、2★ 弧光。"""
        style = style_for(rarity, slot)
        (blx, bly), (brx, _) = quad_local[3], quad_local[2]
        cx = (blx + brx) / 2
        # 5★ 的星芒随前凸立绘一起画，这里跳过。
        if rarity >= 5:
            return
        if rarity == 4:
            # 橙色燃焰
            flame = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            fd = ImageDraw.Draw(flame)
            fd.polygon([(cx - 26 * scale, bly), (cx - 10 * scale, bly - 30 * scale), (cx - 4 * scale, bly - 16 * scale),
                        (cx + 2 * scale, bly - 36 * scale), (cx + 10 * scale, bly - 14 * scale),
                        (cx + 18 * scale, bly - 24 * scale), (cx + 26 * scale, bly)], fill=(255, 126, 34, 240))
            flame = flame.filter(ImageFilter.GaussianBlur(max(1, int(1.2 * scale))))
            canvas.alpha_composite(flame)
        elif rarity == 3:
            # 浅蓝闪电
            bolt = ImageDraw.Draw(canvas)
            bolt.polygon([(cx - 6 * scale, bly - 26 * scale), (cx + 4 * scale, bly - 26 * scale),
                          (cx - 2 * scale, bly - 10 * scale), (cx + 8 * scale, bly - 10 * scale),
                          (cx - 8 * scale, bly + 4 * scale), (cx - 2 * scale, bly - 8 * scale),
                          (cx - 10 * scale, bly - 8 * scale)], fill=(*style["flare"], 235))
        else:
            swoosh = ImageDraw.Draw(canvas)
            swoosh.arc((cx - 20 * scale, bly - 14 * scale, cx + 20 * scale, bly + 6 * scale), 10, 170,
                       fill=(*style["flare"], 220), width=max(2, int(4 * scale)))

    def _front_art(self, canvas: Image.Image, result: PullResult, geometry: CardGeometry, scale: float) -> None:
        """5★ 的立绘不裁进色带，而是完整前凸压在相邻结果上，并在底部补星芒。"""
        style = RARITY_STYLE[max(5, min(5, result.rarity))]
        (tlx, tly), _, (brx, bry), (blx, _) = geometry.quad
        cx = (tlx + tlx + brx + blx) / 4
        width = geometry.width
        height = geometry.height
        art = self.portrait(result.item)
        if art is not None:
            if result.item.kind == "character":
                factor = height * 1.02 / art.height
            else:
                factor = min(width * 0.8 / art.width, height * 0.8 / art.height)
            resized = art.resize((max(1, int(art.width * factor)), max(1, int(art.height * factor))),
                                 Image.Resampling.LANCZOS)
            canvas.alpha_composite(resized, (int(cx - resized.width / 2), int(bry - resized.height)))
        else:
            silhouette = self._silhouette(int(width), int(height), 5, scale)
            canvas.alpha_composite(silhouette, (int(cx - silhouette.width / 2),
                                                int(bry - height * 0.20 - silhouette.height)))

        # 底部星芒：光斑 + 白色四角星
        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        g = ImageDraw.Draw(glow)
        g.ellipse((cx - 52 * scale, bry - 26 * scale, cx + 52 * scale, bry + 22 * scale),
                  fill=(*style["flare"], 190))
        canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(2, int(11 * scale)))))
        star = ImageDraw.Draw(canvas)
        star.polygon([(cx, bry - 40 * scale), (cx + 7 * scale, bry - 5 * scale), (cx + 26 * scale, bry + 2 * scale),
                      (cx + 7 * scale, bry + 9 * scale), (cx, bry + 40 * scale), (cx - 7 * scale, bry + 9 * scale),
                      (cx - 26 * scale, bry + 2 * scale), (cx - 7 * scale, bry - 5 * scale)],
                     fill=(255, 255, 255, 245))
        # 四角星再叠一个更大的柔光
        flare = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(flare).polygon(
            [(cx, bry - 90 * scale), (cx + 4 * scale, bry), (cx + 60 * scale, bry + 2 * scale),
             (cx + 4 * scale, bry + 4 * scale), (cx, bry + 90 * scale), (cx - 4 * scale, bry + 4 * scale),
             (cx - 60 * scale, bry + 2 * scale), (cx - 4 * scale, bry)], fill=(255, 250, 220, 130))
        canvas.alpha_composite(flare.filter(ImageFilter.GaussianBlur(max(2, int(4 * scale)))))

    def _result_card(self, result: PullResult, geometry: CardGeometry, scale: float, art_layer: bool = True,
                     slot: int = 0, with_reward: bool = True, base_alpha: int = 255):
        """返回 (卡片图层, 偏移)，卡片已按色带裁好；art_layer=False 时只画底/框/刻印。

        ``base_alpha`` < 255 时色带底色半透明，用于让 5★ 背后的蓝色身影透出来。
        """
        canvas, offset = self._card_canvas(geometry, scale)
        local = [(px - offset[0], py - offset[1]) for px, py in geometry.quad]
        rarity = max(1, min(5, result.rarity))
        self._card_base(rarity, canvas, local, scale, alpha=base_alpha, slot=slot)
        if art_layer:
            self._place_art(canvas, result.item, geometry, rarity, local, scale, slot=slot)
        self._card_emblem(canvas, local, rarity, scale, slot, with_reward=with_reward,
                          card_scale=geometry.height / 440)
        self._frame(canvas, local, rarity, scale, slot=slot)
        return canvas, offset

    # ------------------------------------------------------------------
    # 顶部 / 右下角装饰
    # ------------------------------------------------------------------
    def _top_hud(self, canvas: Image.Image, scale: float, show_new: bool = True,
                 resources: Sequence[int] = (121, 880, 0)) -> None:
        draw = ImageDraw.Draw(canvas)
        # 相机图标（顶栏左侧）
        cam_x, cam_y = 742 * scale, 10 * scale
        draw.rounded_rectangle((cam_x, cam_y + 4 * scale, cam_x + 30 * scale, cam_y + 24 * scale), radius=4 * scale,
                               outline=(255, 255, 255, 200), width=max(1, int(2 * scale)))
        draw.ellipse((cam_x + 9 * scale, cam_y + 7 * scale, cam_x + 21 * scale, cam_y + 19 * scale),
                     outline=(255, 255, 255, 200), width=max(1, int(2 * scale)))
        draw.rectangle((cam_x + 5 * scale, cam_y, cam_x + 13 * scale, cam_y + 5 * scale),
                       outline=(255, 255, 255, 200), width=max(1, int(2 * scale)))
        if show_new:
            self._new_sticker(canvas, 778 * scale, 22 * scale, scale * 0.78)
        # 三种资源：[晶体] [数量][+]；固定在顶栏，卡片顶边从它下方开始。
        slots = ((1060, (168, 92, 255)), (1340, (120, 96, 255)), (1620, (196, 96, 255)))
        for (x, color), count in zip(slots, resources):
            x *= scale
            draw.polygon([(x, 9 * scale), (x + 10 * scale, 22 * scale), (x, 35 * scale),
                          (x - 10 * scale, 22 * scale)],
                         fill=(*color, 240), outline=(255, 255, 255, 230))
            draw.line((x, 9 * scale, x, 35 * scale), fill=(255, 255, 255, 120), width=max(1, int(1.5 * scale)))
            draw.text((x + 92 * scale, 22 * scale), str(count), font=self.font(int(22 * scale)),
                      fill=(255, 255, 255, 255), anchor="rm")
            bx = x + 140 * scale
            draw.ellipse((bx - 12 * scale, 10 * scale, bx + 12 * scale, 34 * scale), fill=(245, 245, 245, 235))
            draw.line((bx - 6 * scale, 22 * scale, bx + 6 * scale, 22 * scale), fill=(40, 40, 40, 255),
                      width=max(2, int(3 * scale)))
            draw.line((bx, 16 * scale, bx, 28 * scale), fill=(40, 40, 40, 255), width=max(2, int(3 * scale)))

    def _new_sticker(self, canvas: Image.Image, x: float, y: float, scale: float) -> None:
        layer = Image.new("RGBA", (int(160 * scale), int(80 * scale)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        font = self.font(int(40 * scale), latin=True)
        draw.text((14 * scale, 30 * scale), "NEW", font=font, fill=(255, 214, 34, 255), anchor="lm",
                  stroke_width=max(2, int(4 * scale)), stroke_fill=(0, 0, 0, 255))
        layer = layer.rotate(-14, resample=Image.Resampling.BICUBIC, expand=True)
        canvas.alpha_composite(layer, (int(x), int(y) - layer.height // 2))

    def _share_badge(self, canvas: Image.Image, scale: float) -> None:
        draw = ImageDraw.Draw(canvas)
        # 位置与截图一致：右下角、卡片下方留白处。
        x, y = 1432 * scale, 760 * scale
        for dx, dy in ((0, 0), (16 * scale, -12 * scale), (26 * scale, 6 * scale)):
            draw.ellipse((x + dx - 7 * scale, y + dy - 7 * scale, x + dx + 7 * scale, y + dy + 7 * scale),
                         fill=(255, 255, 255, 230))
        draw.line((x, y, x + 26 * scale, y + 6 * scale), fill=(255, 255, 255, 230), width=max(2, int(2.5 * scale)))
        draw.text((x + 40 * scale, y + 34 * scale), "分享", font=self.font(int(26 * scale)),
                  fill=(255, 255, 255, 240))

    def _caption_badge(self, canvas: Image.Image, text: tuple[str, str] | None, scale: float) -> None:
        if not text:
            return
        title, subtitle = text
        x, y = 40 * scale, 300 * scale
        draw = ImageDraw.Draw(canvas)
        box_w = 470 * scale
        panel = [(x + 60 * scale, y), (x + box_w, y + 6 * scale), (x + box_w - 14 * scale, y + 96 * scale),
                 (x, y + 90 * scale)]
        draw.polygon(panel, fill=(0, 0, 0, 225))
        draw.ellipse((x - 18 * scale, y + 22 * scale, x + 52 * scale, y + 92 * scale),
                     fill=(20, 20, 24, 235), outline=(255, 206, 120, 255), width=max(2, int(3 * scale)))
        # 奖杯用形状画，避免依赖字体里的 emoji。
        tx, ty = x + 17 * scale, y + 57 * scale
        draw.polygon([(tx - 14 * scale, ty - 12 * scale), (tx + 14 * scale, ty - 12 * scale),
                      (tx + 7 * scale, ty + 4 * scale), (tx - 7 * scale, ty + 4 * scale)],
                     fill=(255, 196, 88, 255))
        draw.arc((tx - 22 * scale, ty - 12 * scale, tx - 6 * scale, ty + 4 * scale), 270, 90,
                 fill=(255, 196, 88, 255), width=max(2, int(3 * scale)))
        draw.arc((tx + 6 * scale, ty - 12 * scale, tx + 22 * scale, ty + 4 * scale), 90, 270,
                 fill=(255, 196, 88, 255), width=max(2, int(3 * scale)))
        draw.rectangle((tx - 3 * scale, ty + 4 * scale, tx + 3 * scale, ty + 14 * scale), fill=(255, 196, 88, 255))
        draw.rectangle((tx - 10 * scale, ty + 14 * scale, tx + 10 * scale, ty + 19 * scale), fill=(255, 196, 88, 255))
        draw.text((x + 80 * scale, y + 26 * scale), title, font=self.font(int(26 * scale)),
                  fill=(245, 245, 245, 255), anchor="lm")
        draw.text((x + 80 * scale, y + 66 * scale), subtitle, font=self.font(int(24 * scale)),
                  fill=(255, 206, 120, 255), anchor="lm")

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def render_ten(
        self,
        results: Sequence[PullResult],
        banner: Banner | None = None,
        user_name: str = "",
        footer: str = "",
        show_new: bool = True,
        caption: tuple[str, str] | None = None,
        size: tuple[int, int] = (DESIGN_W, DESIGN_H),
    ) -> Image.Image:
        canvas = self._background(size)
        scale = self._scale(size)
        count = min(len(results), len(CARD_LAYOUT))
        if count <= 0:
            # 空结果：只出背景 + HUD，不画任何色带（调用方本不该走到这里，但不能抛异常）。
            if size[0] >= 1200:
                self._top_hud(canvas, scale, show_new=show_new)
            return canvas.convert("RGB")
        drawn = list(results)[:count]
        geometry = [card_geometry(i, drawn[i].rarity, window=count) for i in range(count)]

        # z 序：5★ 蓝影垫底 → 低星色带 → 5★ 色带（压在相邻低星上，被自己的蓝影托底）
        # → 4★/3★/2★ 底部强调 → 5★ 前凸立绘与星芒。
        order = sorted(range(count), key=lambda i: (drawn[i].rarity, i))
        # 5★ 背后那团蓝色身影要先画，否则会被自己的色带盖住。
        for i in order:
            if drawn[i].rarity >= 5:
                self._five_backdrop(canvas, geometry[i], scale)
        for i in order:
            if drawn[i].rarity >= 5:
                continue
            card, (ox, oy) = self._result_card(drawn[i], geometry[i], scale, art_layer=True, slot=i)
            canvas.alpha_composite(card, (int(ox), int(oy)))
        for i in order:
            if drawn[i].rarity >= 5:
                # 5★ 底色半透明，让它背后的蓝色身影透出来；立绘单独前凸后画。
                card, (ox, oy) = self._result_card(drawn[i], geometry[i], scale, art_layer=False, slot=i,
                                                   base_alpha=225)
                canvas.alpha_composite(card, (int(ox), int(oy)))
        for i in order:
            if drawn[i].rarity < 5:
                self._accent(canvas, geometry[i].quad, drawn[i].rarity, scale, slot=i)
        for i in order:
            if drawn[i].rarity >= 5:
                self._front_art(canvas, drawn[i], geometry[i], scale)

        if size[0] >= 1200:
            self._top_hud(canvas, scale, show_new=show_new)
            self._share_badge(canvas, scale)
            self._caption_badge(canvas, caption, scale)
        return canvas.convert("RGB")

    def render_single(
        self,
        result: PullResult,
        banner: Banner | None = None,
        user_name: str = "",
        footer: str = "",
        size: tuple[int, int] = (1200, 905),
    ) -> Image.Image:
        canvas = self._background(size)
        scale = self._scale(size) * 1.35
        geometry = card_geometry(0, result.rarity, window=1)
        card_cx = (geometry.quad[0][0] + geometry.quad[2][0]) / 2
        card_cy = (geometry.top + geometry.quad[2][1]) / 2
        shifted = CardGeometry(
            quad=tuple((px - card_cx + size[0] / 2, py - card_cy + size[1] / 2) for px, py in geometry.quad),
            width=geometry.width,
            height=geometry.height,
        )
        if result.rarity >= 5:
            self._five_backdrop(canvas, shifted, scale)
        card, (ox, oy) = self._result_card(result, shifted, scale, art_layer=result.rarity < 5,
                                           base_alpha=225 if result.rarity >= 5 else 255)
        canvas.alpha_composite(card, (int(ox), int(oy)))
        if result.rarity >= 5:
            self._front_art(canvas, result, shifted, scale)
        else:
            self._accent(canvas, shifted.quad, result.rarity, scale)
        return canvas.convert("RGB")


def _find_font(custom: str | None = None, candidates: Sequence[str] = FONT_CANDIDATES) -> str | None:
    for candidate in ([custom] if custom else []) + list(candidates):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def encode(image: Image.Image, quality: int = 90) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
