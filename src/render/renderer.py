"""P5X 风格抽卡结果渲染。

布局参考游戏内十连结果页（1920×873 设计画布）：

* 10 条倾斜的四边形色带，统一倾角、高低错落、互相遮压；
* 立绘以海报方式贴进色带并被裁切，只有 5★ 会整体前凸盖住相邻结果；
* 仅四五星带辉光、边缘碎光；不显示奖励、数量和底部标识；
* 输出只保留背景与抽卡结果，不叠加游戏顶部资源栏、分享按钮等外围 UI。

参考：``tools/fixtures/gacha_reference.jpg``，可用 ``tools/render_compare.py`` 并排对照。
"""

from __future__ import annotations

import io
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageEnhance

from ..core.mechanics import PullResult
from ..core.models import Banner, Item

DESIGN_W, DESIGN_H = 1920, 873

# 卡内边缘光与卡外背光共用光源；角色身份只改变碎光位置，不改变亮度和光束尺寸。
CARD_LIGHTING = {
    4: {"tint": (255, 206, 76), "halo_alpha": 100, "reach": 62, "haze_alpha": 85},
    5: {"tint": (193, 115, 255), "halo_alpha": 175, "reach": 115, "haze_alpha": 140},
}

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


# 每条色带的底色（按截图：绿、金、红、蓝交错，而不是清一色）。
# 注释里的名字对应参考截图里同位置的卡；抽取结果与它无关，只借用配色节奏。
CARD_PALETTE: tuple[dict, ...] = (
    {"light": (34, 128, 84), "dark": (8, 48, 32), "frame": (196, 244, 214)},   # 1 深绿
    {"light": (206, 156, 28), "dark": (72, 50, 8), "frame": (255, 232, 150)},  # 2 琥珀金
    {"light": (150, 132, 40), "dark": (44, 38, 12), "frame": (232, 214, 140)},  # 3 橄榄金
    {"light": (186, 126, 20), "dark": (62, 40, 6), "frame": (255, 220, 140)},   # 4 金
    {"light": (52, 62, 178), "dark": (12, 14, 60), "frame": (198, 206, 255)},   # 5 靛蓝
    {"light": (44, 54, 168), "dark": (10, 12, 52), "frame": (188, 198, 255)},   # 6 靛蓝
    {"light": (176, 40, 52), "dark": (56, 8, 14), "frame": (255, 190, 196)},    # 7 绯红
    {"light": (196, 150, 22), "dark": (66, 46, 8), "frame": (255, 228, 150)},   # 8 琥珀金
    {"light": (170, 46, 44), "dark": (52, 10, 10), "frame": (255, 186, 180)},   # 9 红
    {"light": (40, 70, 186), "dark": (8, 18, 66), "frame": (186, 206, 255)},    # 10 蓝
)


def palette_for(slot: int, rarity: int) -> dict:
    """取某条卡片的配色：先看这条卡位自带的底色，5★ 再压成深蓝并带金色描边。"""
    base = dict(CARD_PALETTE[slot % len(CARD_PALETTE)])
    if rarity >= 5:
        base.update({"light": (66, 76, 190), "dark": (14, 18, 74), "frame": (255, 236, 150)})
    elif rarity == 4:
        base.update({"light": (222, 168, 40), "dark": (78, 54, 8), "frame": (255, 236, 170)})
    elif rarity == 3:
        base.update({"light": (118, 104, 56), "dark": (44, 40, 20), "frame": (222, 206, 158)})
    return base


def style_for(rarity: int, slot: int = 0) -> dict:
    """按稀有度和序号取配色；色带底色用卡位自带的颜色，徽记等沿用稀有度样式。"""
    if rarity <= 3:
        style = dict(RARITY_STYLE[rarity] if not (rarity == 3 and slot % 2 == 1)
                     else RARITY_ALT_STYLE[3])
    else:
        style = dict(RARITY_STYLE[rarity])
    style.update({k: v for k, v in palette_for(slot, rarity).items() if k in ("light", "dark", "frame")})
    return style
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
# 布局：保留旧坐标的错落节奏，随后重新映射到 1920×873 设计画布。
# x 为色带顶边左端。截图里的色带向左下方倾斜，因此底边必须在顶边左侧。
# ---------------------------------------------------------------------------
SLANT = -164
CARD_LAYOUT: tuple[tuple[int, int, int, int], ...] = (
    # (x, width, top, bottom)。最终横坐标会按实际抽取结果重新紧密排列。
    (260, 156, 148, 744),
    (402, 156, 174, 778),
    (544, 156, 146, 752),
    (686, 156, 116, 728),
    (828, 156, 126, 758),
    (970, 156, 108, 738),
    (1112, 156, 136, 756),
    (1254, 156, 158, 780),
    (1396, 156, 122, 730),
    (1538, 156, 144, 750),
)

# 宽屏参考画幅重新布局，非对最终图像纵向拉伸；所有素材仍按原宽高比绘制。
CARD_LAYOUT = tuple((x, w, round((top * 1.18 + 24) * DESIGN_H / 1080), round((bottom * 1.18 + 24) * DESIGN_H / 1080))
                    for x, w, top, bottom in CARD_LAYOUT)

FOUNDATION_RARITY_STYLE = {
    2: {"light": (15, 111, 76), "dark": (3, 45, 29), "width": 142, "grow_top": 0, "grow_bottom": 0},
    3: {"light": (103, 101, 23), "dark": (37, 37, 5), "width": 142, "grow_top": 0, "grow_bottom": 0},
    4: {"light": (153, 114, 32), "dark": (45, 31, 8), "width": 142, "grow_top": 0, "grow_bottom": 0},
    # 5★ 使用接近钻石折射的冷白蓝紫色，后续星级贴图会继续覆盖在其上。
    5: {"light": (33, 39, 108), "dark": (12, 9, 47), "width": 154, "grow_top": 34, "grow_bottom": 50},
}
# 5★ 的前凸量（相对自身色带，按比例）
FIVE_STAR_BOOST = {"width": 1.06, "height": 1.06, "dx": -0.03, "top": 16}
# 高低错落已经写入布局表；只保留极小的水平扰动，避免破坏截图测得的轮廓。
JITTER = ((0, 0),) * 10


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


def foundation_geometry(index: int, rarity: int, window: int | None = None) -> CardGeometry:
    """按物品星级放大底版，同时保持卡位中心不动、相邻卡片不接触。"""
    base = card_geometry(index, 2, window=window)
    rarity = max(2, min(5, rarity))
    spec = FOUNDATION_RARITY_STYLE[rarity]
    target_width = 134 if rarity < 5 else spec["width"]
    dx = (target_width - base.width) / 2
    (tlx, tly), (_trx, _), (_brx, bry), (blx, _) = base.quad
    top = tly - spec["grow_top"]
    bottom = bry + spec["grow_bottom"]
    if rarity >= 5:
        # 实机最高星卡片约占全图九成高度，保留上下各5%的呼吸空间。
        top, bottom = DESIGN_H * .05, DESIGN_H * .95
    return CardGeometry(
        quad=((tlx - dx, top), (tlx - dx + target_width, top),
              (blx - dx + target_width, bottom), (blx - dx, bottom)),
        width=target_width,
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
                source = source.convert("RGB")
                red, green, blue = source.split()
                # 去掉旧素材烘焙的纯蓝切线，位置由独立矢量层控制。
                blue_mask = ImageChops.subtract(blue, ImageChops.lighter(red, green)).point(
                    lambda value: 255 if value > 55 else 0)
                source.paste((6, 7, 10), (0, 0, source.width, source.height), blue_mask)
                # 等比覆盖裁切；避免旧宽屏底图被纵向拉长，蓝色切线随原图等比保留。
                canvas = ImageOps.fit(source.convert("RGB"), size, Image.Resampling.LANCZOS,
                                      centering=(0.5, 0.5))
                canvas = ImageEnhance.Brightness(canvas).enhance(.88).convert("RGBA")
        else:
            canvas = Image.new("RGBA", size, (5, 6, 9, 255))
        self._blue_cutlines(canvas)
        self._background_cache[size] = canvas
        return canvas.copy()

    @staticmethod
    def _blue_cutlines(canvas: Image.Image) -> None:
        """按主参考归一化坐标绘制；不跟随拼贴背景裁切，也不受光效覆盖。"""
        width, height = canvas.size
        def points(values):
            return [(round(x*width), round(y*height)) for x,y in values]
        blue = (0, 38, 196, 255)
        overlay = Image.new("RGBA", canvas.size)
        draw = ImageDraw.Draw(overlay)
        # 左上网格仅出现在斜切条上方。
        grid = Image.new("RGBA", canvas.size)
        gd = ImageDraw.Draw(grid)
        for n in range(-2, 14):
            x = n*.065
            gd.line(points(((x,0),(x+.065,.115))), fill=blue, width=max(1,round(width*.003)))
            gd.line(points(((x,0),(x-.065,.115))), fill=blue, width=max(1,round(width*.003)))
        mask = Image.new("L", canvas.size)
        ImageDraw.Draw(mask).polygon(points(((0,0),(.62,0),(0,.087))), fill=255)
        overlay.alpha_composite(Image.composite(grid, Image.new("RGBA", canvas.size), mask))
        draw = ImageDraw.Draw(overlay)
        draw.polygon(points(((0,.084),(.347,.035),(.329,.024),(.62,0),
                             (.395,.025),(.362,.041),(0,.109))), fill=blue)
        draw.polygon(points(((.345,1),(.582,.962),(.568,.953),(1,.904),
                             (1,.927),(.610,.972),(.625,.980))), fill=blue)
        canvas.alpha_composite(overlay)

    @staticmethod
    def _scale(size: tuple[int, int]) -> float:
        return size[0] / DESIGN_W

    # ------------------------------------------------------------------
    # 色带
    # ------------------------------------------------------------------
    def _card_canvas(self, geometry: CardGeometry, scale: float) -> tuple[Image.Image, tuple[int, int]]:
        # 低星底部的横向长楔会向左伸出约 0.7 个卡宽，局部画布必须留足空间。
        pad = int(128 * scale) + 8
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

    def _character_pair(self, item):
        if item.kind not in ("character", "char"):
            return None
        code = item.id.split(":", 1)[-1].casefold()
        code = {"j&c": "jandc", "leon": "leo"}.get(code, code)
        root = self.assets / "character_layers"
        mapping_path = root / "mapping.json"
        if not hasattr(self, "_character_mapping"):
            self._character_mapping = (json.loads(mapping_path.read_text(encoding="utf-8"))
                                       if mapping_path.is_file() else {})
        entry = self._character_mapping.get(item.id)
        if entry:
            def runtime_path(name):
                prepared = root / "prepared" / name
                return prepared if prepared.is_file() else root / name
            front = runtime_path(entry["front"])
            back = runtime_path(entry["back"]) if entry.get("back") else None
            if front.is_file() and (back is None or back.is_file()):
                return front, back
        files = {p.name.casefold(): p for p in root.glob("*.png")}
        front = files.get(f"lihui-guaidao-{code}.png")
        back_name = {"joker": "joker-02-new", "marian": "marian02"}.get(code, code+"-02")
        back = files.get(f"lihui-guaidao-{back_name}.png")
        return (front, back) if front and back else None

    def _source_art(self, path):
        if not hasattr(self, "_source_cache"):
            self._source_cache = {}
        key = str(path)
        if key not in self._source_cache:
            if len(self._source_cache) >= 12:
                self._source_cache.pop(next(iter(self._source_cache)))
            with Image.open(path) as source:
                self._source_cache[key] = source.convert("RGBA")
        return self._source_cache[key]

    def _placement(self, item):
        if not hasattr(self, "_placements"):
            path = self.assets / "character_layers" / "placement.json"
            self._placements = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return self._placements.get(item.id)

    @staticmethod
    def _visible_resize(art, factor, x, y, geometry):
        """只重采样卡槽可见范围，避免放大数倍的整张立绘占用时间与内存。"""
        width, height = max(1, round(art.width*factor)), max(1, round(art.height*factor))
        x, y = round(x), round(y)
        left = max(x, int(min(p[0] for p in geometry.quad))-4)
        top = max(y, int(geometry.top)-4)
        right = min(x+width, int(max(p[0] for p in geometry.quad))+5)
        bottom = min(y+height, int(max(p[1] for p in geometry.quad))+5)
        if right <= left or bottom <= top:
            return Image.new("RGBA", (1,1)), (left,top)
        box = ((left-x)*art.width/width, (top-y)*art.height/height,
               (right-x)*art.width/width, (bottom-y)*art.height/height)
        return art.resize((right-left,bottom-top), Image.Resampling.LANCZOS, box=box), (left,top)

    def _anchored_foreground(self, art, placement, geometry):
        bounds = art.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()
        if bounds:
            art = art.crop(bounds)
        fx, fy = placement["face"]
        factor = geometry.width * .95 / (art.width * placement["face_width"])
        factor = min(factor, geometry.height * 3.7 / art.height)
        tl, tr, br, bl = geometry.quad
        target_y = .42
        lane_x = (tl[0] + tr[0]) / 2 + (bl[0] - tl[0]) * target_y
        x = lane_x - round(art.width*factor)*fx
        y = tl[1]+geometry.height*target_y-round(art.height*factor)*fy
        return self._visible_resize(art, factor, x, y, geometry)

    def _character_art(self, pair, geometry, scale, item=None):
        """前景按逐角色脸部锚点定位，避免举手、武器与披风挤走人物。"""
        canvas, offset = self._card_canvas(geometry, scale)
        tl, tr, br, bl = geometry.quad
        placement = self._placement(item) if item else None
        placement = placement or {"face": [.5,.13], "face_width": .20}
        if pair[1] is not None:
            back = self._source_art(pair[1])
            bounds = back.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()
            if bounds:
                back = back.crop(bounds)
            bp = placement.get("background", {"face": [.5,.2], "face_width": .22})
            bx, by = bp["face"]
            factor = min(geometry.width * 1.22 / (back.width * bp["face_width"]), geometry.height * 4.5 / back.height)
            target_y = bp.get("target_y", .13)
            lane_x = (tl[0]+tr[0])/2+(bl[0]-tl[0])*target_y
            x = lane_x-round(back.width*factor)*bx
            y = tl[1]+geometry.height*target_y-round(back.height*factor)*by
            back, (x,y) = self._visible_resize(back,factor,x,y,geometry)
            back = ImageEnhance.Brightness(back).enhance(1.16)
            canvas.alpha_composite(back,(x-offset[0],y-offset[1]))
        if "jandc" in pair[0].stem.casefold():
            self._twins_foreground(canvas, offset, pair[0], geometry)
            return canvas, offset
        art = self._source_art(pair[0])
        art, (x,y) = self._anchored_foreground(art, placement, geometry)
        front = Image.new("RGBA",canvas.size)
        front.alpha_composite(art,(x-offset[0],y-offset[1]))
        # 上方保留专属人格面具的面部；前景从头发上沿渐入，避免举手武器盖住后景。
        alpha = front.getchannel("A")
        gate = Image.new("L",canvas.size,255)
        draw = ImageDraw.Draw(gate)
        cutoff = round(tl[1]+geometry.height*.255-offset[1])
        draw.rectangle((0,0,canvas.width,max(0,cutoff)),fill=0)
        fade = max(1,round(geometry.height*.025))
        for row in range(fade):
            draw.line((0,cutoff+row,canvas.width,cutoff+row),fill=round(255*row/fade))
        front.putalpha(ImageChops.multiply(alpha,gate))
        canvas.alpha_composite(front)
        return canvas, offset

    @staticmethod
    def _twins_foreground(canvas, offset, path, geometry):
        """按双人原图的分界拆成两个前景，分别锚定脸部，不将整张横向挤入窄槽。"""
        with Image.open(path) as source:
            art = source.convert("RGBA")
        w, h = art.size
        seam = [(w*.64,0),(w*.64,h*.22),(w*.48,h*.34),
                (w*.40,h*.55),(w*.25,h)]
        left = Image.new("L", art.size)
        ImageDraw.Draw(left).polygon([(0,0),*seam,(0,h)],fill=255)
        tl,tr,br,bl = geometry.quad
        # 两张脸分别占上、下半区，尺度按脸宽约占槽宽的 68% 确定。
        factor = geometry.width*.92/(w*.17)
        for mask, face, target_y in ((left,(.32,.15),.40),
                                    (ImageOps.invert(left),(.63,.385),.68)):
            figure = art.copy()
            figure.putalpha(ImageChops.multiply(art.getchannel("A"),mask))
            figure = figure.resize((max(1,round(w*factor)),max(1,round(h*factor))),
                                   Image.Resampling.LANCZOS)
            lane_x = (tl[0]+tr[0])/2+(bl[0]-tl[0])*target_y
            x = lane_x-w*face[0]*factor
            y = tl[1]+geometry.height*target_y-h*face[1]*factor
            canvas.alpha_composite(figure,(round(x-offset[0]),round(y-offset[1])))

    def art_layer(self, result: PullResult, geometry: CardGeometry, scale: float, slot: int = 0
                  ) -> tuple[Image.Image, tuple[int, int]] | None:
        """生成**不受色带裁切**的立绘图层（返回图层与左上角坐标）。

        参考截图里立绘是主体、色带只是衬在后面的布料：人物顶到卡顶甚至越出色带，
        左右也可以探出到相邻卡片上。所以立绘必须是独立的前层，不能塞进多边形里裁。
        """
        pair = self._character_pair(result.item)
        if pair:
            return self._character_art(pair, geometry, scale, result.item)
        art = self.portrait(result.item)
        placement = self._placement(result.item) if result.item.kind in ("char", "character") else None
        if art is not None and placement:
            return self._anchored_foreground(art, placement, geometry)
        width, height = geometry.width, geometry.height
        (tlx, tly), (trx, _), (brx, bry), (blx, _) = geometry.quad
        cx = (tlx + trx + brx + blx) / 4

        if art is None:
            # 缺图：用收在色带中央的角色型剪影兜底。不能铺满整张卡，否则十连会变成
            # 十块相同的深色墓碑，完全盖掉参考图最重要的彩色色带节奏。
            silhouette = self._silhouette(int(width * 0.72), int(height * 0.76), result.rarity, scale,
                                          slot=slot, fill=True)
            layer = Image.new("RGBA", silhouette.size, (0, 0, 0, 0))
            layer.alpha_composite(silhouette)
            return layer, (int(cx - silhouette.width / 2), int(bry - silhouette.height * 0.96))

        bounds = art.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()
        if bounds:
            art = art.crop(bounds)
        if result.item.kind == "persona":
            if not hasattr(self, "_persona_placements"):
                path = self.assets / "persona_placement.json"
                self._persona_placements = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            placement = self._persona_placements.get(result.item.id, {})
            focus = placement.get("focus", [.5,.3])
            if placement.get("flip_x"):
                art = ImageOps.mirror(art)
            # 小幅宽度让步保留主体大小；翅膀和尾巴可以裁切，脸部必须留在槽内。
            factor = min(height * placement.get("max_height", 1.16) / art.height, width * placement.get("max_width", 2.3) / art.width)
            resized = art.resize((max(1,round(art.width*factor)),max(1,round(art.height*factor))), Image.Resampling.LANCZOS)
            subject_y = tly + height * placement.get("target_y", .29)
            y = subject_y - resized.height * focus[1]
            ratio = (subject_y-tly)/height
            lane_x = (tlx+trx)/2+(blx-tlx)*ratio
            x = lane_x-resized.width*focus[0]
            # 细黑衬线提升同色属性底纹上的轮廓，不给低星添加辉光。
            alpha = resized.getchannel("A")
            outline = alpha.filter(ImageFilter.MaxFilter(3))
            under = Image.new("RGBA",resized.size,(5,7,12,0))
            under.putalpha(outline.point(lambda a: round(a*.65)))
            under.alpha_composite(resized)
            return under,(round(x),round(y))
        if result.item.kind in ("character", "char", "persona"):
            # 角色：按身高铺满整张卡，再上浮 6%，让头探出卡顶（参考图里头顶都越界）。
            factor = height * 1.55 / art.height
            # 宽而近圆的面具按轮廓宽度适配，避免被当作瘦长人物无限放大。
            if result.item.kind == "persona" and art.width / art.height > 0.70:
                factor = min(factor, width * 2.8 / art.width)
        else:
            # 武器：原比例放进卡片，横向不超过卡宽的 86%，避免枪管被切。
            factor = min(width * 0.86 / art.width, height * 0.78 / art.height)
        resized = art.resize((max(1, int(art.width * factor)), max(1, int(art.height * factor))),
                             Image.Resampling.LANCZOS)
        y = int(bry - height * 0.025 - resized.height)
        if result.item.kind in ("char", "character"):
            y = round(tly+height*.08)
        if resized.height < height * 0.72:
            y = int(tly + (height - resized.height) * 0.62)
        # 以每张立绘上半部的可见像素重心定位，避免宽幅披风/武器把脸挤出色带。
        alpha = resized.getchannel("A")
        focus_h = max(1, int(resized.height * 0.18))
        focus = alpha.crop((0, 0, resized.width, focus_h)).resize((64, 32))
        weights = list(focus.getdata())
        mass = sum(weights)
        focus_x = sum((i % 64 + 0.5) * value for i, value in enumerate(weights)) / max(1, mass)
        focus_x = focus_x / 64 * resized.width
        subject_y = y + focus_h * 0.5
        ratio = max(0.0, min(1.0, (subject_y - tly) / max(1, height)))
        lane_x = (tlx + trx) / 2 + (blx - tlx) * ratio
        x = int(lane_x - focus_x)
        # 角色头部优先完整落在色带内，左右预留黑边安全区。
        if result.item.kind in ("char", "character"):
            head_box = alpha.crop((0, 0, resized.width, focus_h)).getbbox()
            if head_box:
                lane_left = tlx + (blx - tlx) * ratio + 10
                lane_right = trx + (brx - trx) * ratio - 10
                if head_box[2] - head_box[0] <= lane_right - lane_left:
                    x = int(max(lane_left-head_box[0], min(x, lane_right-head_box[2])))
        return resized, (x, y)

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
                    fill: bool = False, slot: int = 0, overflow: bool = False) -> Image.Image:
        """剪影：暗色长袍 + 头 + 角；``palette="blue"`` 时是 5★ 背后那团蓝色身影。

        ``overflow=True`` 时按整角高度铺满（用于「立绘应当站起来、顶到卡顶」的场景）。
        """
        if palette == "blue":
            # 蓝影要撑满整条色带：头在上部，肩膀展开到接近全宽。
            return self._monster_silhouette(width, height, scale)
        style = style_for(rarity, slot)
        w = int(width * (1.0 if (fill or overflow) else 0.66))
        h = int(height * (1.0 if (fill or overflow) else 0.60))
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

    @staticmethod
    def _effect_phase(item_id: str, slot: int) -> float:
        digest = hashlib.sha256(f"{item_id}:{slot}".encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") / 4294967296

    @staticmethod
    def _effect_segments(phase: float, rarity: int):
        if rarity < 4:
            return ()
        segments = ((0, .08+phase*.07, .12+phase*.07),
                    (0, .85-phase*.09, .91-phase*.09))
        return segments + ((1, .23+phase*.11, .27+phase*.11),) if rarity >= 5 else segments

    def _five_flare(self, canvas: Image.Image, geometry: CardGeometry, scale: float, rarity: int = 5,
                    item_id: str = "", slot: int = 0) -> None:
        """沿色带边缘的稀有度光效，不把星芒排成底部徽章。"""
        if rarity < 4:
            return
        points = [(x * scale, y * scale) for x, y in geometry.quad]
        lighting = CARD_LIGHTING[5 if rarity >= 5 else 4]
        tint = lighting["tint"]
        halo = Image.new("RGBA", canvas.size)
        hd = ImageDraw.Draw(halo)
        inner_points = _inner_quad(points, 14 * scale)
        # 柔光集中在顶底，而非整圈灯管。确定性相位让相邻高星不重复。
        phase = self._effect_phase(item_id, slot)
        for t in (.03, .94):
            alpha = lighting["halo_alpha"]
            a, b = inner_points[0], inner_points[3]
            x = a[0]+(b[0]-a[0])*t + geometry.width*scale*.475
            y = a[1]+(b[1]-a[1])*t
            reach = (60 if rarity >= 5 else 35) * scale
            hd.polygon([(x-8*scale,y-reach),(x+10*scale,y-reach),
                        (x-6*scale,y+reach),(x-18*scale,y+reach)], fill=(*tint,alpha))
        radius = max(2, int(17 * scale))
        bounds = halo.getbbox()
        if bounds:
            pad = radius*4
            region = (max(0,bounds[0]-pad),max(0,bounds[1]-pad),
                      min(canvas.width,bounds[2]+pad),min(canvas.height,bounds[3]+pad))
            glow = halo.crop(region)
            glow_size = glow.size
            # 大半径柔光在半分辨率计算，细亮边和星芒仍以原分辨率绘制。
            glow = glow.resize((max(1,glow.width//2),max(1,glow.height//2)),Image.Resampling.BILINEAR)
            glow = glow.filter(ImageFilter.GaussianBlur(radius/2)).resize(glow_size,Image.Resampling.BILINEAR)
            canvas.alpha_composite(glow,region[:2])
        edge = ImageDraw.Draw(canvas)
        # 光边位于黑色分隔线内侧；仍保留黑缝，不做整圈白色相框。
        for side, lo, hi in self._effect_segments(phase, rarity):
            a, b = points[side], points[3-side]
            inset = 16 * scale if side == 0 else -16 * scale
            segment = [(a[0]+(b[0]-a[0])*t+inset, a[1]+(b[1]-a[1])*t) for t in (lo, hi)]
            edge.line(segment, fill=(*tint, 240), width=max(2, int(4 * scale)))
            if rarity >= 5:
                edge.line(segment, fill=(243, 236, 255, 245), width=max(1, int(2 * scale)))
            # 碎光只围绕局部亮边，不沿全卡均匀撒点。
            for n in range(2 if rarity >= 5 else 1):
                t = lo+(hi-lo)*(.2+.5*n)
                x = a[0]+(b[0]-a[0])*t+inset+(n*2-1)*5*scale
                y = a[1]+(b[1]-a[1])*t
                r = (2+n)*scale
                edge.polygon(((x-r,y-r),(x+r,y-r*.5),(x,y+r*2)), fill=(*tint,210))
        for side, t, strength in ((0, .83-phase*.13, 1.0), (1, .19+phase*.16, .65)):
            if rarity == 4 and side == 1:
                continue
            a, b = points[side], points[3-side]
            x, y = a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t
            x += (18 if side == 0 else -18) * scale
            r = (24 if rarity >= 5 else 11) * scale * strength
            edge.polygon([(x,y-r),(x+r*.12,y-r*.12),(x+r*.70,y),
                          (x+r*.12,y+r*.12),(x,y+r),(x-r*.12,y+r*.12),
                          (x-r*.70,y),(x-r*.12,y-r*.12)], fill=(255,252,245,245))

    def _high_star_backlight(self, canvas, geometries, results, scale):
        """卡外顶底光束先画在背景上，所有底版及黑衬底均遮挡它。"""
        haze = Image.new("RGBA", canvas.size)
        rays = Image.new("RGBA", canvas.size)
        hd, rd = ImageDraw.Draw(haze), ImageDraw.Draw(rays)
        for slot, (geo, result) in enumerate(zip(geometries, results)):
            if result.rarity < 4:
                continue
            lighting = CARD_LIGHTING[5 if result.rarity >= 5 else 4]
            color = lighting["tint"]
            reach = lighting["reach"] * scale
            for end in (0, 1):
                a, b = (geo.quad[0], geo.quad[1]) if end == 0 else (geo.quad[3], geo.quad[2])
                cx, y = (a[0]+b[0])*.5*scale, a[1]*scale
                sign = -1 if end == 0 else 1
                dx = -sign * 22 * scale
                half = geo.width * scale * (.31 if result.rarity >= 5 else .19)
                hd.polygon([(cx-half,y),(cx+half,y),(cx+dx+half*.4,y+sign*reach),
                            (cx+dx-half*.4,y+sign*reach)], fill=(*color,lighting["haze_alpha"]))
                for n in range(4 if result.rarity>=5 else 2):
                    x = cx+(n-1.5)*13*scale + (slot%3)*4*scale
                    rd.line([(x,y),(x+dx,y+sign*reach*(.55+.1*((slot+n)%4)))],
                            fill=(*color,100), width=max(1,int(scale)))
        canvas.alpha_composite(haze.filter(ImageFilter.GaussianBlur(max(2,int(17*scale)))))
        canvas.alpha_composite(rays.filter(ImageFilter.GaussianBlur(max(.5,scale*.65))))

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

    def _native_foundation(self, canvas, quad, rarity, element, kind, scale):
        """原始结果底纹；品质贴图沿用现有轮廓试合成，不推断游戏材质参数。"""
        names = {"火焰": "huo", "电击": "dian", "冰冻": "bin", "疾风": "feng",
                 "核热": "he", "念动": "nian", "诅咒": "zhou", "祝福": "zhu",
                 "物理": "wu", "射击": "she", "万能": "wan"}
        root = self.assets / "gacha_native"
        filename = (f"character-bg-{5 if rarity >= 5 else 4}.png" if kind in ("character", "char") else
                    f"chouka-jieguo-wuqidi{3 if rarity >= 5 else 2 if rarity == 4 else 1}.png"
                    if kind == "weapon" else
                    f"chouka-jieguo-xibie-{names.get(element, 'wan')}.png")
        path = root / filename
        if not path.is_file():
            return False
        tl, tr, br, bl = quad
        width, height = max(1, tr[0]-tl[0]), max(1, bl[1]-tl[1])
        shear = (bl[0]-tl[0]) / height
        def warp(image):
            # 解包 PNG 已含倾斜透明外沿；按有效色带映射，不能再倾斜一次。
            alpha = image.getchannel("A")
            y1, y2 = round(image.height*.1), round(image.height*.9)
            row1 = alpha.crop((0, y1, image.width, y1+1)).getbbox()
            row2 = alpha.crop((0, y2, image.width, y2+1)).getbbox()
            source_shear = (row2[0]-row1[0]) / (y2-y1) if row1 and row2 else 0
            source_left = row1[0]-source_shear*y1 if row1 else 0
            source_width = ((row1[2]-row1[0]+row2[2]-row2[0])/2
                            if row1 and row2 else image.width)
            sx, sy = source_width / width, image.height / height
            xy = -shear*sx + source_shear*sy
            return image.transform(canvas.size, Image.Transform.AFFINE,
                                   (sx, xy, source_left-tl[0]*sx-tl[1]*xy,
                                    0, sy, -tl[1]*sy),
                                   Image.Resampling.BICUBIC)
        clip = Image.new("L", canvas.size)
        ImageDraw.Draw(clip).polygon(_polygon(quad), fill=255)
        source = self._source_art(path)
        if kind in ("character", "char") and rarity >= 5:
            if not hasattr(self, "_five_foundation_source"):
                self._five_foundation_source = source.transform(
                    (360, 828), Image.Transform.QUAD,
                    (120, 27, 15, 647, 290, 685, 372, 35), Image.Resampling.BICUBIC)
            source = self._five_foundation_source
        layer = warp(source)
        layer.putalpha(ImageChops.multiply(layer.getchannel("A"), clip))
        if kind != "character_edge":
            canvas.alpha_composite(layer)
        if rarity >= 4 and kind not in ("character", "char"):
            quality = root / ("chouka-jieguo-pinzhicai.png" if rarity >= 5
                              else "chouka-jieguo-pinzhijin.png")
            if quality.is_file():
                # 品质层只露出窄边，不能覆盖属性底纹或黑色衬底。
                ring = Image.new("L", canvas.size)
                ImageDraw.Draw(ring).line(_polygon(quad + [quad[0]]), fill=255,
                                         width=max(3, round(5*scale)), joint="curve")
                with Image.open(quality) as source:
                    edge = warp(source.convert("RGBA"))
                edge.putalpha(ImageChops.multiply(edge.getchannel("A"),
                              ImageChops.multiply(ring, clip)))
                canvas.alpha_composite(edge)
        return True

    def _character_frame(self, canvas, geometry, rarity, scale=1):
        """原始左边+底边品质框，最后覆盖立绘；右侧黑分隔不参与该框映射。"""
        path = self.assets / "gacha_native" / f"character-frame-{5 if rarity >= 5 else 4}.png"
        if not path.is_file() or rarity < 4:
            return
        tl, tr, br, bl = [(x*scale, y*scale) for x,y in geometry.quad]
        x0 = max(0, int(min(tl[0],bl[0]))-8)
        y0 = max(0, int(tl[1])-8)
        x1 = min(canvas.width, int(max(tr[0],br[0]))+9)
        y1 = min(canvas.height, int(bl[1])+9)
        local_size = (max(1,x1-x0),max(1,y1-y0))
        tl,tr,br,bl = [(x-x0,y-y0) for x,y in (tl,tr,br,bl)]
        # 与底纹使用完全一致的内轮廓，右、下留出黑衬底。
        border = max(5, round(7*scale))
        tr = (tr[0]-border, tr[1])
        br = (br[0]-border, br[1]-border)
        bl = (bl[0]+(tl[0]-bl[0])*border/max(1, bl[1]-tl[1]), bl[1]-border)
        width, height = tr[0]-tl[0], bl[1]-tl[1]
        shear = (bl[0]-tl[0])/height
        image = self._source_art(path)
        # 不能按 alpha 每行的宽度拟合：描边每行只有几个像素，并非整张卡宽。
        source_left = image.width-1
        source_shear = -source_left/image.height
        sx, sy = 184/width, image.height/height
        xy = -shear*sx+source_shear*sy
        edge = image.transform(local_size, Image.Transform.AFFINE,
                               (sx,xy,source_left-tl[0]*sx-tl[1]*xy,0,sy,-tl[1]*sy),
                               Image.Resampling.BICUBIC)
        clip = Image.new("L", local_size)
        ImageDraw.Draw(clip).polygon(_polygon([tl,tr,br,bl]),fill=255)
        edge.putalpha(ImageChops.multiply(edge.getchannel("A"),clip))
        canvas.alpha_composite(edge,(x0,y0))

    def _foundation_card(self, geometry: CardGeometry, scale: float, slot: int, rarity: int, element: str = "",
                         kind: str = "persona"):
        """左侧、顶侧色带直达边缘，仅右侧与底部保留黑色衬底。"""
        canvas, offset = self._card_canvas(geometry, scale)
        local = [(px - offset[0], py - offset[1]) for px, py in geometry.quad]
        border = max(5, int(7 * scale))
        points = _polygon(local)

        # 底版不携带外扩辉光；高星光效在独立层合成，避免染亮相邻低星和黑缝。

        draw = ImageDraw.Draw(canvas)
        # 不是四边相框：上、左不缩进，右、下才留黑色衬底。
        draw.polygon(points, fill=(2, 2, 4, 255))
        tl, tr, br, bl = local
        inner = [tl, (tr[0]-border, tr[1]),
                 (br[0]-border, br[1]-border),
                 (bl[0]+(tl[0]-bl[0])*border/max(1, bl[1]-tl[1]), bl[1]-border)]
        # 角色使用用户指定的紫色/金色底纹，品质框在立绘与黑分隔之后单独合成。
        if kind in ("character", "char"):
            self._native_foundation(canvas, inner, rarity, "", kind, scale)
            return canvas, offset
        palette = FOUNDATION_RARITY_STYLE[max(2, min(5, rarity))]
        element_colors = {
            "火焰": ((174, 103, 13), (65, 29, 2)),
            "电击": ((163, 151, 10), (50, 47, 2)),
            "冰冻": ((24, 78, 153), (5, 21, 65)),
            "疾风": ((15, 133, 94), (3, 47, 33)),
            "诅咒": ((151, 30, 43), (55, 5, 14)),
            "核热": ((150, 103, 24), (55, 32, 3)),
            "念动": ((122, 49, 131), (39, 11, 50)),
            "祝福": ((175, 144, 29), (63, 46, 5)),
            "物理": ((159, 114, 15), (66, 37, 3)),
            "射击": ((140, 109, 20), (49, 34, 4)),
            "万能": ((75, 83, 102), (21, 24, 34)),
        }
        if kind == "weapon" and rarity < 4:
            palette = {"light": (24, 100, 41), "dark": (4, 38, 15)}
        elif rarity < 4 and element in element_colors:
            light, dark = element_colors[element]
            palette = {"light": light, "dark": dark}
        self._fill_gradient(canvas, inner, palette["light"], palette["dark"], slope=False)
        texture = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        td = ImageDraw.Draw(texture)
        cell_w, cell_h = max(4, round(17 * scale)), max(7, round(29 * scale))
        for row, ty in enumerate(range(0, canvas.height + cell_h, cell_h)):
            for tx in range(-cell_w, canvas.width + cell_w, cell_w):
                px = tx + (cell_w // 2 if row % 2 else 0)
                td.polygon([(px, ty-cell_h//2), (px+cell_w//2, ty),
                            (px, ty+cell_h//2), (px-cell_w//2, ty)],
                           fill=(255, 255, 255, 7 if (row + tx//cell_w) % 2 else 2))
        texture_mask = Image.new("L", canvas.size)
        ImageDraw.Draw(texture_mask).polygon(_polygon(inner), fill=255)
        canvas.alpha_composite(Image.composite(texture, Image.new("RGBA", canvas.size), texture_mask))
        # 有原图时彻底替换合成底纹，避免原生菱形与程序菱形重叠。
        native = Image.new("RGBA", canvas.size)
        if self._native_foundation(native, inner, rarity, element, kind, scale):
            ImageDraw.Draw(canvas).polygon(_polygon(inner), fill=(2, 2, 4, 255))
            canvas.alpha_composite(native)
        if rarity in (2, 3):
            foot = self._low_star_foot(geometry, 1)
            ImageDraw.Draw(canvas).polygon([(x-offset[0], y-offset[1]) for x,y in foot],
                                           fill=(2, 2, 4, 255))
        return canvas, offset

    @staticmethod
    def _low_star_foot(geometry: CardGeometry, scale: float) -> list[tuple[float, float]]:
        """低星底部黑楔：左端收尖，右端变厚，彩色色带下沿斜向右上。"""
        tl, tr, br, bl = geometry.quad
        rise = min(geometry.height * .075, geometry.width * .28)
        right_x = br[0] + (tr[0]-br[0]) * rise / max(1, geometry.height)
        extension = 18 * scale
        return [(bl[0]*scale, bl[1]*scale+extension), (br[0]*scale, br[1]*scale+extension),
                (right_x*scale, (br[1]-rise)*scale)]

    def _result_rewards(self, canvas, geometry, rarity, scale):
        """参考结果页的横条奖励结构；图标使用本地绘制近似。"""
        tl, tr, br, bl = geometry.quad
        draw = ImageDraw.Draw(canvas)
        for row in range(1 if rarity == 4 else 2):
            y = bl[1] - (100 - row * 44) * scale
            ratio = (y - tl[1]) / geometry.height
            cx = (tl[0] + tr[0]) / 2 + (bl[0] - tl[0]) * ratio
            w, h = min(geometry.width * 0.78, 105) * scale, 34 * scale
            color = (58, 38, 125) if rarity == 5 and row == 0 else ((148, 91, 8) if row == 0 else (9, 63, 148))
            draw.polygon([(cx-w/2+5,y-h/2),(cx+w/2,y-h/2),
                          (cx+w/2-5,y+h/2),(cx-w/2,y+h/2)], fill=(*color,245))
            ix = cx - w * 0.18
            draw.ellipse((ix-17*scale,y-16*scale,ix+17*scale,y+16*scale),
                         fill=(240,185,44) if row == 0 else (110,200,245), outline="white",width=2)
            if row == 0:
                draw.polygon([(ix,y-12*scale),(ix+11*scale,y+9*scale),(ix-11*scale,y+6*scale)],
                             fill=(181,105,245) if rarity == 5 else (255,239,131),outline="white")
            else:
                draw.ellipse((ix-6*scale,y-10*scale,ix+6*scale,y+2*scale),fill="white")
                draw.arc((ix-10*scale,y-4*scale,ix+7*scale,y+11*scale),0,230,fill="white",width=4)
            draw.text((cx+w*0.29,y),str(15 if rarity == 4 else 30) if row == 0 else "1",
                      font=self.font(max(10,int(18*scale))),fill="white",anchor="mm",stroke_width=2,stroke_fill="black")

    @staticmethod
    def _centered_result_slots(results: Sequence[PullResult]) -> list[PullResult]:
        """5★占正中央，4★占中央两侧，低星从外侧向内填充。"""
        count = len(results)
        five_slots = [5, 4, 6, 3, 7, 2, 8, 1, 9, 0]
        four_slots = [4, 6, 3, 7, 2, 8, 1, 9, 0, 5]
        low_slots = [0, 9, 1, 8, 2, 7, 3, 6, 4, 5]
        preferences = {5: five_slots, 4: four_slots, 3: low_slots, 2: low_slots}
        slots: list[PullResult | None] = [None] * count
        ranked = sorted(enumerate(results), key=lambda pair: (-pair[1].rarity, pair[0]))
        for _source, result in ranked:
            preferred = preferences[max(2, min(5, result.rarity))]
            target = next(index for index in preferred if index < count and slots[index] is None)
            slots[target] = result
        return [result for result in slots if result is not None]

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

    def _user_panel(self, canvas, user_name, footer, avatar):
        """斜切身份签与契约计数：沿用背景的黑、白、电蓝视觉。"""
        if not user_name and not footer:
            return
        import re
        scale = canvas.width / DESIGN_W
        if canvas.width >= 1500:
            scale *= .60  # 宽屏左下留白内显示，避开90%高度的中央五星。
        layer = Image.new("RGBA", (DESIGN_W, 1080))
        draw = ImageDraw.Draw(layer)
        # 底部留白内独立排版；短切口与背景斜线呼应。
        draw.polygon([(48,978),(564,955),(541,1045),(26,1060)],fill=(0,0,0,245))
        draw.polygon([(44,966),(554,944),(535,1031),(27,1048)],fill=(244,245,248,255))
        draw.polygon([(52,974),(131,970),(115,1035),(35,1040)],fill=(0,38,196,255))
        face = None
        if avatar:
            try:
                with Image.open(io.BytesIO(avatar)) as source:
                    face = ImageOps.fit(source.convert("RGBA"), (66,66), Image.Resampling.LANCZOS)
            except Exception:
                pass
        if face is None:
            face = Image.new("RGBA",(66,66),(16,22,45,255))
            ImageDraw.Draw(face).text((33,33),(user_name or "玩")[0],font=self.font(36),anchor="mm",fill="white")
        mask = Image.new("L",(66,66))
        ImageDraw.Draw(mask).polygon([(9,0),(65,0),(56,65),(0,65)],fill=255)
        layer.paste(face,(53,973),mask)
        name = " ".join((user_name or "玩家").split())
        font = self.font(32)
        while len(name)>1 and draw.textlength(name,font=font)>355:
            name = name[:-2]+"…"
        remaining = re.search(r"今日剩余\s*(\d+)\s*抽", footer)
        if remaining:
            draw.text((147,968),f"今日可抽 {remaining.group(1)} 抽",font=self.font(20),fill=(0,38,196))
        else:
            draw.text((147,970),"PHANTOM  /  CONTRACT",font=self.font(13,latin=True),fill=(0,38,196))
        draw.text((143,990),name,font=font,fill=(9,11,18))
        progress = re.search(r"(\d+)\s*/\s*(\d+)",footer)
        total = re.search(r"累计\s*(\d+)\s*抽",footer)
        if progress:
            current, hard = map(int,progress.groups())
            draw.polygon([(610,965),(1000,965),(983,1040),(592,1040)],fill=(0,0,0,235))
            draw.polygon([(614,960),(627,960),(610,1036),(597,1036)],fill=(0,57,240,255))
            draw.text((642,970),"保底进度",font=self.font(19),fill=(190,198,216))
            draw.text((800,960),str(current),font=self.font(56,latin=True),fill="white")
            draw.text((888,988),f"/ {hard}",font=self.font(27,latin=True),fill=(175,186,215))
            # 细分进度条只有当前保底填充，五星重置后归空。
            draw.polygon([(639,1027),(953,1027),(950,1032),(638,1032)],fill=(52,57,75))
            fill_width = round(311*min(1,current/max(1,hard)))
            if fill_width:
                draw.rectangle((640,1027,640+fill_width,1032),fill=(47,87,255))
        if total:
            draw.polygon([(1050,965),(1350,965),(1333,1040),(1032,1040)],fill=(0,0,0,225))
            draw.text((1070,975),"累计契约",font=self.font(19),fill=(190,198,216))
            # 避免大累计值挤出面板。
            number=total.group(1); font=self.font(46,latin=True)
            while draw.textlength(number,font=font)>100 and font.size>18:
                font=self.font(font.size-1,latin=True)
            draw.polygon([(1053,1030),(1068,1030),(1065,1035),(1050,1035)],fill=(0,57,240))
            draw.text((1190,963),number,font=font,fill="white")
            draw.text((1304,1014),"抽",font=self.font(16),fill=(190,198,216))
        if canvas.size != layer.size:
            layer = layer.resize((round(DESIGN_W * scale), round(1080 * scale)),Image.Resampling.LANCZOS)
        canvas.alpha_composite(layer, (0, canvas.height - layer.height))

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
        avatar: bytes | None = None,
    ) -> Image.Image:
        if size != (DESIGN_W, DESIGN_H):
            # 先在设计坐标完成构图，再等比缩放/留边；不改变立绘定位算法。
            full = self.render_ten(results, banner, user_name, footer, show_new, caption, avatar=avatar)
            return ImageOps.pad(full, size, Image.Resampling.LANCZOS, color=(5,6,9))
        canvas = self._background(size)
        scale = self._scale(size)
        count = min(len(results), len(CARD_LAYOUT))
        if count <= 0:
            # 空结果只返回背景（调用方本不该走到这里，但不能抛异常）。
            return canvas.convert("RGB")
        # 第一阶段只校准十个独立底版。高星仅决定居中次序、底色和辉光，不改变几何。
        arranged = self._centered_result_slots(list(results)[:count])
        geometry = [foundation_geometry(i, arranged[i].rarity, window=count) for i in range(count)]
        # 左侧无描边，因此不能再让下一张向左压住前一张的右侧黑衬底。
        # 保留窄缝，也为高低差造成的斜率差异留出安全距离。
        border_overlap = -4.0
        total_width = sum(item.width for item in geometry) - border_overlap * max(0, count - 1)
        cursor = (DESIGN_W - total_width - SLANT) / 2
        packed: list[CardGeometry] = []
        for item in geometry:
            top = item.quad[0][1]
            bottom = item.quad[3][1]
            packed.append(CardGeometry(
                quad=((cursor, top), (cursor + item.width, top),
                      (cursor + SLANT + item.width, bottom), (cursor + SLANT, bottom)),
                width=item.width,
                height=item.height,
            ))
            cursor += item.width - border_overlap
        geometry = packed
        self._high_star_backlight(canvas, geometry, arranged, scale)
        # 各物品独立合成，立绘受自身色带约束，黑边始终清晰分隔十个结果。
        for i in range(count):
            result = arranged[i]
            foundation, (fox, foy) = self._foundation_card(geometry[i], scale, i, result.rarity,
                                                         result.item.element, result.item.kind)
            canvas.alpha_composite(foundation, (int(fox), int(foy)))
            mask = Image.new("L", canvas.size, 0)
            points = [(int(px * scale), int(py * scale)) for px, py in geometry[i].quad]
            ImageDraw.Draw(mask).polygon(points, fill=255)
            content = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            layer = self.art_layer(result, geometry[i], scale, slot=i)
            if layer is not None:
                art, (ax, ay) = layer
                content.alpha_composite(art, (int(ax), int(ay)))
            canvas.alpha_composite(Image.composite(content, Image.new("RGBA", canvas.size), mask))
            if result.rarity in (2, 3):
                ImageDraw.Draw(canvas).polygon(self._low_star_foot(geometry[i], scale),
                                               fill=(2, 2, 4, 255))
            outline = points[1:3] if result.rarity < 4 else points[1:]
            ImageDraw.Draw(canvas).line(outline, fill=(2, 2, 4, 255), width=max(5, int(8 * scale)), joint="curve")

        for i in range(count):
            result = arranged[i]
            if result.rarity >= 4:
                effects = Image.new("RGBA", canvas.size)
                effects_mask = Image.new("L", canvas.size)
                points = [(px * scale, py * scale) for px, py in geometry[i].quad]
                ImageDraw.Draw(effects_mask).polygon(points, fill=255)
                self._five_flare(effects, geometry[i], scale, result.rarity, result.item.id, i)
                canvas.alpha_composite(Image.composite(effects, Image.new("RGBA", canvas.size), effects_mask))

        # 光效只能落在高星底版内部；低星与卡间黑线不接受光效。
        self._draw_separators(canvas, geometry, scale, [result.rarity for result in arranged])
        for geo, result in zip(geometry, arranged):
            if result.item.kind in ("character", "char"):
                self._character_frame(canvas, geo, result.rarity, scale)
        self._blue_cutlines(canvas)
        self._user_panel(canvas, user_name, footer, avatar)

        return canvas.convert("RGB")

    @staticmethod
    def _draw_separators(canvas: Image.Image, geometries: Sequence[CardGeometry], scale: float,
                         rarities: Sequence[int] | None = None) -> None:
        """只补回可见轮廓，后方色带的边线不能穿过前方色带。"""
        polygons = [[(int(x * scale), int(y * scale)) for x, y in geo.quad]
                    for geo in geometries]
        borders = Image.new("L", canvas.size)
        draw = ImageDraw.Draw(borders)
        # 与底版采用同一遮挡顺序：先擦除被新色带覆盖的旧线，再画新线。
        for index, points in enumerate(polygons):
            draw.polygon(points, fill=0)
            outline = points[1:3] if rarities and rarities[index] < 4 else points[1:]
            draw.line(outline, fill=255,
                      width=max(5, int(8 * scale)), joint="curve")
        black = Image.new("RGBA", canvas.size, (2, 2, 4, 255))
        canvas.paste(black, (0, 0), borders)

    def render_single(
        self,
        result: PullResult,
        banner: Banner | None = None,
        user_name: str = "",
        footer: str = "",
        size: tuple[int, int] = (1200, 905),
        avatar: bytes | None = None,
    ) -> Image.Image:
        canvas = self._background(size)
        scale = 1.0
        # 单抽使用更宽的主视觉卡槽；几何直接采用输出坐标。
        width, height = size[0] * .27, size[1] * (.90 if result.rarity >= 5 else .78)
        top, slant = size[1] * (.05 if result.rarity >= 5 else .08), -size[0] * .09
        left = size[0] / 2 - width / 2 - slant / 2
        shifted = CardGeometry(
            quad=((left,top),(left+width,top),(left+width+slant,top+height),(left+slant,top+height)),
            width=width, height=height,
        )
        self._high_star_backlight(canvas, [shifted], [result], 1)
        # 单抽同样走「色带 + 独立立绘前层」，保证立绘顶到卡顶而不是被裁进色带。
        card, (ox, oy) = self._foundation_card(shifted, scale, 0, result.rarity, result.item.element, result.item.kind)
        canvas.alpha_composite(card, (int(ox), int(oy)))
        layer = self.art_layer(result, shifted, scale)
        if layer is not None:
            art, (ax, ay) = layer
            content = Image.new("RGBA",canvas.size)
            content.alpha_composite(art,(int(ax),int(ay)))
            mask = Image.new("L",canvas.size)
            ImageDraw.Draw(mask).polygon(shifted.quad,fill=255)
            canvas.alpha_composite(Image.composite(content,Image.new("RGBA",canvas.size),mask))
        if result.rarity in (2, 3):
            ImageDraw.Draw(canvas).polygon(self._low_star_foot(shifted, 1), fill=(2, 2, 4, 255))
        if result.rarity >= 4:
            # 单抽底版已经是输出像素坐标，光效不能再乘一次画布缩放。
            effects = Image.new("RGBA", canvas.size)
            self._five_flare(effects, shifted, 1, result.rarity, result.item.id)
            mask = Image.new("L", canvas.size)
            ImageDraw.Draw(mask).polygon(shifted.quad, fill=255)
            canvas.alpha_composite(Image.composite(effects, Image.new("RGBA", canvas.size), mask))
        self._draw_separators(canvas, [shifted], 1, [result.rarity])
        if result.item.kind in ("character", "char"):
            self._character_frame(canvas, shifted, result.rarity)
        self._blue_cutlines(canvas)
        self._user_panel(canvas, user_name, footer, avatar)
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
