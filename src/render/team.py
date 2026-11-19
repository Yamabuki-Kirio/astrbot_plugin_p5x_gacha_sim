"""Team collection posters with adjacent owner/weapon groups and capped progress."""
from collections import defaultdict
import math
from PIL import Image, ImageDraw, ImageOps, ImageFilter
from .roster import _fit_text
from .renderer import CardGeometry

COLUMNS = 6
ROWS_PER_PAGE = 4
VIEW_W = 1920
VIEW_H = 1080
STAGE_W = 1997
STAGE_H = 826
CARD_BODY_W = 286
CARD_H = 788
CARD_SKEW = 189
CARD_GAP = 15
HEADER_H = 152
FOOTER_H = 74

def team_rows(entries):
    groups = defaultdict(list)
    for entry in entries:
        groups[entry.owner].append(entry)
    def group_key(pair):
        owner, group = pair
        character = next((e for e in group if e.item.id.startswith('char:')), None)
        return (character is None, -(character.item.rarity if character else max(e.item.rarity for e in group)),
                character.item.name if character else owner)
    ordered = []
    for owner, group in sorted(groups.items(), key=group_key):
        group.sort(key=lambda e:(not e.item.id.startswith('char:'), -e.item.rarity, e.item.name, e.item.id))
        ordered.extend(group)
    return tuple(tuple(ordered[n:n+COLUMNS]) for n in range(0, len(ordered), COLUMNS))


def team_pages(entries):
    rows = team_rows(entries)
    return tuple(rows[n:n+ROWS_PER_PAGE] for n in range(0,len(rows),ROWS_PER_PAGE)) or ((),)


def _spark(draw, x, y, radius, color):
    points=[]
    for n in range(8):
        angle=-math.pi/2+n*math.pi/4
        r=radius if n%2==0 else radius*.17
        points.append((x+math.cos(angle)*r,y+math.sin(angle)*r))
    draw.polygon(points,fill=color)


def _star_points(cx, cy, outer_r, inner_r, rot_deg=-90):
    pts = []
    for i in range(10):
        ang = math.radians(rot_deg + i * 36)
        r = outer_r if i % 2 == 0 else inner_r
        pts.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r))
    return pts


def _star_background(size):
    w, h = size
    bg = Image.new('RGBA', (w, h), (12, 12, 15, 255))
    tile_n = 156
    tile = Image.new('RGBA', (tile_n, tile_n), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    c = tile_n / 2
    td.polygon(_star_points(c, c, 64, 27), outline=(29, 29, 36, 255), width=3)
    td.polygon(_star_points(c, c, 40, 17), outline=(29, 29, 36, 160), width=2)
    pad = int(math.hypot(w, h) * 0.25) + tile_n
    pw, ph = w + pad * 2, h + pad * 2
    pattern = Image.new('RGBA', (pw, ph), (0, 0, 0, 0))
    for yy in range(0, ph, tile_n):
        for xx in range(0, pw, tile_n):
            pattern.paste(tile, (xx, yy))
    rotated = pattern.rotate(-12, resample=Image.Resampling.BICUBIC)
    ox = (rotated.width - w) // 2
    oy = (rotated.height - h) // 2
    bg.alpha_composite(rotated.crop((ox, oy, ox + w, oy + h)))
    return bg


def _progress_icon(renderer, entry, size=66):
    """Load the generated 0-6 consciousness/evolution emblem for a collection card."""
    kind = 'consciousness' if entry.item.id.startswith('char:') else 'weapon'
    path = renderer._runtime_asset(
        renderer.assets / 'progression_icons' / f'{kind}-{entry.level}.png')
    cache = getattr(renderer, '_progress_icon_cache', None)
    if cache is None:
        cache = renderer._progress_icon_cache = {}
    key = (kind, entry.level, size)
    if key not in cache:
        with Image.open(path) as source:
            icon = source.convert('RGBA')
            bounds = icon.getchannel('A').getbbox()
            if bounds:
                icon = icon.crop(bounds)
            icon = ImageOps.contain(icon, (size, size), Image.Resampling.LANCZOS)
        cache[key] = icon
    return cache[key].copy()


def _owner_character(item, registry):
    owner = item if item.id.startswith('char:') else registry.item(entry_owner_id(item))
    if owner and (owner.meta.get('position') or owner.element):
        return owner
    # 部分特殊版本没有重复填写属性/职业，沿用同代号基础角色的数据。
    code = item.id.partition(':')[2].split('-weapon', 1)[0].split('·', 1)[0]
    return registry.item('char:' + code) or owner


def entry_owner_id(item):
    if item.id.startswith('char:'):
        return item.id
    return 'char:' + item.id.partition(':')[2].split('-weapon', 1)[0]


def _fit_layer(art, size, centering, scale=1.0):
    art = art.convert('RGBA')
    bounds = art.getchannel('A').getbbox()
    if bounds:
        art = art.crop(bounds)
    target = (max(1, round(size[0] * scale)), max(1, round(size[1] * scale)))
    fitted = ImageOps.fit(art, target, Image.Resampling.LANCZOS, centering=centering)
    canvas = Image.new('RGBA', size)
    canvas.alpha_composite(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
    return canvas


def _lane_center_x(y):
    return CARD_SKEW * (1.0 - y / CARD_H) + CARD_BODY_W * 0.5


def _place_anchored(art, canvas_size, art_area_h, face, face_width,
                    target_y, card_face_ratio, min_h_ratio, max_h_ratio, dx=0.0):
    art = art.convert('RGBA')
    bounds = art.getchannel('A').point(lambda v: 255 if v > 16 else 0).getbbox()
    if bounds:
        art = art.crop(bounds)
    fx, fy = face
    fw = max(0.05, float(face_width))
    factor = CARD_BODY_W * card_face_ratio / (art.width * fw)
    factor = max(factor, art_area_h * min_h_ratio / art.height)
    factor = min(factor, art_area_h * max_h_ratio / art.height)
    rw, rh = max(1, round(art.width * factor)), max(1, round(art.height * factor))
    resized = art.resize((rw, rh), Image.Resampling.LANCZOS)
    subject_y = art_area_h * target_y
    lane_x = _lane_center_x(subject_y) + dx
    x = round(lane_x - rw * fx)
    y = round(subject_y - rh * fy)
    layer = Image.new('RGBA', canvas_size, (0, 0, 0, 0))
    layer.alpha_composite(resized, (x, y))
    return layer


def _cover_art(renderer, item, size):
    art_area_h = CARD_H - 104
    if item.id.startswith('char:'):
        pair = renderer._character_pair(item)
        if pair:
            placement = renderer._placement(item) or {'face': [0.5, 0.15], 'face_width': 0.20}
            canvas = Image.new('RGBA', size, (0, 0, 0, 0))
            if pair[1] is not None:
                bp = placement.get('background', {'face': [0.5, 0.2], 'face_width': 0.22})
                bg_layer = _place_anchored(
                    renderer._source_art(pair[1]), size, art_area_h,
                    bp.get('face', [0.5, 0.2]), bp.get('face_width', 0.22),
                    target_y=0.11, card_face_ratio=0.66, min_h_ratio=1.15, max_h_ratio=3.0, dx=22.0
                )
                canvas.alpha_composite(bg_layer)
            fg_layer = _place_anchored(
                renderer._source_art(pair[0]), size, art_area_h,
                placement.get('face', [0.5, 0.15]), placement.get('face_width', 0.20),
                target_y=0.25, card_face_ratio=0.48, min_h_ratio=1.20, max_h_ratio=2.8, dx=0.0
            )
            canvas.alpha_composite(fg_layer)
            return canvas
        art = renderer.portrait(item)
        if art:
            placement = renderer._placement(item)
            if placement:
                return _place_anchored(
                    art, size, art_area_h,
                    placement.get('face', [0.5, 0.15]), placement.get('face_width', 0.20),
                    target_y=0.25, card_face_ratio=0.48, min_h_ratio=1.20, max_h_ratio=2.8, dx=0.0
                )
    else:
        art = renderer.portrait(item)
    if not art:
        return None
    return _fit_layer(art, size, (.5, .20), 1.05)


def _team_card(renderer, entry, registry):
    card_w = CARD_BODY_W + CARD_SKEW
    quad = ((CARD_SKEW, 0), (card_w, 0), (CARD_BODY_W, CARD_H), (0, CARD_H))
    mask = Image.new('L', (card_w, CARD_H), 0)
    ImageDraw.Draw(mask).polygon(quad, fill=255)
    card = Image.new('RGBA', (card_w, CARD_H), (0, 0, 0, 0))

    art_area_h = CARD_H - 104
    background = Image.new('RGBA', card.size, (20, 20, 26, 255))
    bd = ImageDraw.Draw(background)
    for y in range(art_area_h):
        t = y / max(1, art_area_h - 1)
        color = tuple(round(39 + (19 - 39) * t) if channel == 0 else
                      round(43 + (21 - 43) * t) if channel == 1 else
                      round(61 + (31 - 61) * t) for channel in range(3))
        bd.line((0, y, card_w, y), fill=(*color, 255))
    art = _cover_art(renderer, entry.item, (card_w, CARD_H))
    if art:
        background.alpha_composite(art, (0, 0))
    card.alpha_composite(Image.composite(background, Image.new('RGBA', card.size), mask))

    footer_y = CARD_H - 104
    overlay = Image.new('RGBA', card.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.polygon([(25, footer_y), (CARD_BODY_W + 25, footer_y), (CARD_BODY_W, CARD_H), (0, CARD_H)],
               fill=(5, 5, 7, 255))
    od.line([(25, footer_y), (CARD_BODY_W + 25, footer_y)], fill='white', width=4)
    card.alpha_composite(overlay)

    owner = _owner_character(entry.item, registry)
    if owner and owner.element:
        key = owner.element.replace('/', '_')
        path = renderer.assets / 'element_icons' / f'{key}.png'
        if path.is_file():
            source = renderer._source_art(path)
            icon = ImageOps.contain(source.crop(source.getchannel('A').getbbox()),
                                    (56, 56), Image.Resampling.LANCZOS)
            card.alpha_composite(icon, (28, footer_y + 6 + (56 - icon.height) // 2))
    progress = _progress_icon(renderer, entry, size=56)
    card.alpha_composite(progress, (CARD_BODY_W - 58, footer_y + 6))

    draw = ImageDraw.Draw(card)
    level = 100 if entry.maxed else 80
    draw.text((16, CARD_H - 13), entry.item.name,
              font=_fit_text(renderer, draw, entry.item.name, CARD_BODY_W - 105, 22), anchor='lb', fill='white')
    draw.text((CARD_BODY_W - 8, CARD_H - 12), f'Lv{level}', font=renderer.font(24, latin=True),
              anchor='rb', fill='white')
    draw.line(list(quad) + [quad[0]], fill=(5, 5, 7, 255), width=7)
    if entry.item.id.startswith('char:') and entry.item.rarity in (4, 5):
        art_quad = (quad[0], quad[1], (CARD_BODY_W + 25, footer_y), (25, footer_y))
        renderer._character_frame(card, CardGeometry(art_quad, CARD_BODY_W, footer_y), entry.item.rarity)
    return card


def _render_row(renderer, row, registry):
    viewport = _star_background((VIEW_W, VIEW_H))
    stage = Image.new('RGBA', (STAGE_W, STAGE_H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stage)
    shadow = Image.new('RGBA', stage.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(0, 4), (STAGE_W, 4), (STAGE_W - 30, STAGE_H), (0, STAGE_H)],
                                   fill=(0, 0, 0, 210))
    stage.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)), (0, 14))
    sd.polygon([(0, 4), (STAGE_W, 4), (STAGE_W - 30, STAGE_H), (0, STAGE_H)], fill=(10, 38, 184, 255))

    start_x = 100
    card_y = 17
    step = CARD_BODY_W + CARD_GAP
    for index, entry in enumerate(row):
        card = _team_card(renderer, entry, registry)
        layout_x = start_x + index * step
        stage.alpha_composite(card, (layout_x - CARD_SKEW // 2, card_y))

    tilted = stage.rotate(4.2, resample=Image.Resampling.BICUBIC, expand=True)
    viewport.alpha_composite(tilted, ((VIEW_W - tilted.width) // 2, (VIEW_H - tilted.height) // 2))
    return viewport


def render_team(renderer, rows, registry, user_name, page, pages, character_count, weapon_count,
                remaining, avatar=None):
    images = [_render_row(renderer, row, registry) for row in rows] if rows else [_star_background((VIEW_W, VIEW_H))]
    height = HEADER_H + VIEW_H * len(images) + FOOTER_H
    stitched = _star_background((VIEW_W, height)).convert('RGB')
    for index, image in enumerate(images):
        stitched.paste(image.convert('RGB'), (0, HEADER_H + index * VIEW_H))

    draw = ImageDraw.Draw(stitched)
    draw.polygon([(0, 0), (VIEW_W, 0), (VIEW_W, 128), (0, HEADER_H)], fill=(7, 10, 22))
    draw.polygon([(0, 144), (VIEW_W, 120), (VIEW_W, 129), (0, 153)], fill=(10, 38, 184))
    draw.text((48, 18), 'PHANTOM / COLLECTION', font=renderer.font(21, latin=True), fill=(139, 157, 255))
    draw.text((46, 48), '我的队伍 · 收藏名册', font=renderer.font(44), fill='white')
    draw.text((48, 104), f'角色 {character_count} 位  /  武器 {weapon_count} 件  ·  今日可抽 {remaining} 抽',
              font=renderer.font(23), fill=(200, 210, 245))
    draw.text((VIEW_W - 48, 22), f'{page:02d} / {pages:02d}', font=renderer.font(24, latin=True),
              anchor='ra', fill='white')
    name = ' '.join((user_name or '玩家').split())[:30]
    draw.text((VIEW_W - 48, 68), name, font=_fit_text(renderer, draw, name, 520, 26), anchor='ra', fill='white')

    if not rows:
        center_y = HEADER_H + VIEW_H // 2
        draw.text((VIEW_W // 2, center_y - 20), '尚未获得四、五星角色或武器',
                  font=renderer.font(38), anchor='mm', fill='white')
        draw.text((VIEW_W // 2, center_y + 42), '发送 /十连 开始收集你的队伍',
                  font=renderer.font(26), anchor='mm', fill=(157, 173, 235))

    footer_y = height - FOOTER_H
    draw.line([(48, footer_y + 18), (VIEW_W - 48, footer_y + 18)], fill=(10, 38, 184), width=3)
    draw.text((48, footer_y + 36), '首次 0/6 · 第七次 6/6 · 满阶重复返还10抽',
              font=renderer.font(21), fill='white')
    draw.text((VIEW_W - 48, footer_y + 36), '/队伍 页码' if pages > 1 else '意识 / 进化',
              font=renderer.font(20), anchor='ra', fill=(165, 178, 232))
    return stitched

