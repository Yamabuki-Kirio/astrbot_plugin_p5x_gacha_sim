"""Team collection posters with adjacent owner/weapon groups and capped progress."""
from collections import defaultdict
import io
import math
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps
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
    rows, row = [], []
    for owner, group in sorted(groups.items(), key=group_key):
        group.sort(key=lambda e:(not e.item.id.startswith('char:'), -e.item.rarity, e.item.name, e.item.id))
        if row and len(row) + len(group) > COLUMNS:
            rows.append(tuple(row))
            row = []
        while len(group) > COLUMNS:
            rows.append(tuple(group[:COLUMNS]))
            group = group[COLUMNS:]
        row.extend(group)
        if len(row) == COLUMNS:
            rows.append(tuple(row))
            row = []
    if row:
        rows.append(tuple(row))
    return tuple(rows)


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


def _asset_icon(renderer, path, box):
    if not path.is_file():
        return None
    source = renderer._source_art(path)
    bounds = source.getchannel('A').getbbox()
    if bounds:
        source = source.crop(bounds)
    return ImageOps.contain(source, box, Image.Resampling.LANCZOS)


def _element_icons(renderer, owner, size=50):
    if not owner or not owner.element:
        return ()
    names = [part.strip() for part in owner.element.split('/') if part.strip()]
    icon_size = size if len(names) == 1 else round(size * .72)
    icons = []
    for name in names[:2]:
        icon = _asset_icon(renderer, renderer.assets / 'element_icons' / f'{name}.png',
                           (icon_size, icon_size))
        if icon:
            icons.append(icon)
    return tuple(icons)


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


def _fit_weapon_art(art, size, art_area_h, rarity):
    """Display weapons completely inside the slanted lane with subtle glow and shadow."""
    art = art.convert('RGBA')
    bounds = art.getchannel('A').point(lambda v: 255 if v > 16 else 0).getbbox()
    if bounds:
        art = art.crop(bounds)
    max_w = max(1, round(CARD_BODY_W * 0.90))
    max_h = max(1, round(art_area_h * 0.74))
    resized = ImageOps.contain(art, (max_w, max_h), Image.Resampling.LANCZOS)
    subject_y = art_area_h * 0.48
    lane_x = _lane_center_x(subject_y)
    cx, cy = round(lane_x), round(subject_y)
    x = round(lane_x - resized.width / 2)
    y = round(subject_y - resized.height / 2)

    canvas = Image.new('RGBA', size, (0, 0, 0, 0))
    glow = Image.new('RGBA', size, (0, 0, 0, 0))
    glow_color = (146, 102, 255, 76) if rarity >= 5 else (238, 182, 64, 68)
    rx = round(CARD_BODY_W * 0.52)
    ry = round(art_area_h * 0.30)
    ImageDraw.Draw(glow).ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=glow_color)
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(38)))

    shadow_alpha = resized.getchannel('A').point(lambda a: round(a * 0.62))
    shadow = Image.new('RGBA', resized.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    shadow_layer = Image.new('RGBA', size, (0, 0, 0, 0))
    shadow_layer.alpha_composite(shadow, (x + 8, y + 12))
    canvas.alpha_composite(shadow_layer.filter(ImageFilter.GaussianBlur(10)))
    canvas.alpha_composite(resized, (x, y))
    return canvas


def _weapon_frame(card, art_quad, rarity):
    """Draw a sleek left+bottom rarity accent edge for 4★/5★ weapon cards."""
    if rarity < 4:
        return
    tl, _tr, br, bl = art_quad
    overlay = Image.new('RGBA', card.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    # Inset slightly inside the 7px outer black border
    inset_x = 6
    inset_y = 4
    p_top = (tl[0] + inset_x, tl[1] + inset_y)
    p_bot = (bl[0] + inset_x, bl[1] - inset_y)
    p_right = (br[0] - inset_x, br[1] - inset_y)
    if rarity >= 5:
        stops = ((110, 212, 255), (188, 122, 255), (255, 164, 240))
    else:
        stops = ((255, 236, 152), (242, 186, 68), (212, 140, 28))
    steps = 36
    for i in range(steps):
        t0, t1 = i / steps, (i + 1) / steps
        tm = (t0 + t1) * 0.5
        if tm < 0.5:
            k = tm * 2
            c = tuple(round(stops[0][j] * (1 - k) + stops[1][j] * k) for j in range(3))
        else:
            k = (tm - 0.5) * 2
            c = tuple(round(stops[1][j] * (1 - k) + stops[2][j] * k) for j in range(3))
        x0 = p_top[0] + (p_bot[0] - p_top[0]) * t0
        y0 = p_top[1] + (p_bot[1] - p_top[1]) * t0
        x1 = p_top[0] + (p_bot[0] - p_top[0]) * t1
        y1 = p_top[1] + (p_bot[1] - p_top[1]) * t1
        od.line([(x0, y0), (x1, y1)], fill=(*c, 245), width=6)
    od.line([p_bot, p_right], fill=(*stops[2], 235), width=5)
    glow = overlay.filter(ImageFilter.GaussianBlur(4))
    glow.putalpha(glow.getchannel('A').point(lambda a: round(a * 0.55)))
    card.alpha_composite(glow)
    card.alpha_composite(overlay)


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
        if art:
            return _fit_weapon_art(art, size, art_area_h, item.rarity)
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
    is_char = entry.item.id.startswith('char:')
    if is_char:
        top_rgb, bot_rgb = (39, 43, 61), (19, 21, 31)
    elif entry.item.rarity >= 5:
        top_rgb, bot_rgb = (44, 34, 78), (15, 13, 30)
    else:
        top_rgb, bot_rgb = (54, 44, 28), (20, 17, 14)

    background = Image.new('RGBA', card.size, (20, 20, 26, 255))
    bd = ImageDraw.Draw(background)
    for y in range(art_area_h):
        t = y / max(1, art_area_h - 1)
        color = tuple(round(top_rgb[ch] + (bot_rgb[ch] - top_rgb[ch]) * t) for ch in range(3))
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
    divider_color = ((224, 184, 255) if entry.item.rarity >= 5 else (255, 224, 128)) if entry.maxed else 'white'
    od.line([(25, footer_y), (CARD_BODY_W + 25, footer_y)], fill=divider_color, width=4)
    card.alpha_composite(overlay)

    owner = _owner_character(entry.item, registry)
    icon_x = 24
    for icon in _element_icons(renderer, owner, size=50):
        card.alpha_composite(icon, (icon_x, footer_y + 9 + (50 - icon.height) // 2))
        icon_x += icon.width + 4
    progress = _progress_icon(renderer, entry, size=60)
    card.alpha_composite(progress, (CARD_BODY_W - 65, footer_y + 4))

    draw = ImageDraw.Draw(card)
    level = 100 if entry.maxed else 80
    level_color = (255, 224, 120) if entry.maxed else 'white'
    draw.text((16, CARD_H - 13), entry.item.name,
              font=_fit_text(renderer, draw, entry.item.name, CARD_BODY_W - 108, 22), anchor='lb', fill='white')
    draw.text((CARD_BODY_W - 8, CARD_H - 12), f'Lv{level}', font=renderer.font(24, latin=True),
              anchor='rb', fill=level_color)
    draw.line(list(quad) + [quad[0]], fill=(5, 5, 7, 255), width=7)
    art_quad = (quad[0], quad[1], (CARD_BODY_W + 25, footer_y), (25, footer_y))
    if is_char and entry.item.rarity in (4, 5):
        renderer._character_frame(card, CardGeometry(art_quad, CARD_BODY_W, footer_y), entry.item.rarity)
    elif not is_char and entry.item.rarity in (4, 5):
        _weapon_frame(card, art_quad, entry.item.rarity)
    return card


def _team_background(renderer, size, flip=False):
    """Use the rich P5X monochrome mask/star/halftone background (matching gacha & in-game team UI)."""
    cache = getattr(renderer, '_team_bg_cache', None)
    if cache is None:
        cache = renderer._team_bg_cache = {}
    key = (size, bool(flip))
    if key in cache:
        return cache[key].copy()
    path = renderer._runtime_asset(renderer.assets / 'p5x-gacha-background-v1.png')
    if path.is_file():
        with Image.open(path) as source:
            source = source.convert('RGB')
            red, green, blue = source.split()
            # Strip the baked blue cutlines so only the pure dark monochrome P5X pattern remains.
            blue_mask = ImageChops.subtract(blue, ImageChops.lighter(red, green)).point(
                lambda v: 255 if v > 42 else 0)
            # Slightly expand the mask by 1px to avoid any residual blue fringe
            blue_mask = blue_mask.filter(ImageFilter.MaxFilter(3))
            source.paste((8, 9, 13), (0, 0, source.width, source.height), blue_mask)
            if flip:
                source = ImageOps.mirror(source)
            canvas = ImageOps.fit(source, size, Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            # Lift contrast gently so the dark star/mask texture reads crisply like the in-game team backdrop
            canvas = ImageEnhance.Contrast(canvas).enhance(1.18)
            canvas = ImageEnhance.Brightness(canvas).enhance(1.06).convert('RGBA')
    else:
        canvas = _star_background(size)
    cache[key] = canvas
    return canvas.copy()


def _render_row(renderer, row, registry, row_index=0):
    viewport = _team_background(renderer, (VIEW_W, VIEW_H), flip=(row_index % 2 == 1))
    bezel = 20
    stage_h = CARD_H + bezel * 2
    stage = Image.new('RGBA', (STAGE_W, stage_h), (0, 0, 0, 0))
    outer_quad = [(0, 0), (STAGE_W, 0), (STAGE_W - 28, stage_h), (0, stage_h)]
    inner_quad = [(0, bezel), (STAGE_W, bezel), (STAGE_W - 28, stage_h - bezel), (0, stage_h - bezel)]

    shadow = Image.new('RGBA', stage.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(outer_quad, fill=(0, 0, 0, 220))
    stage.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(24)), (0, 12))

    # Bold jet-black P5X outer bezel + clean, solid Velvet royal blue band (matching official in-game team UI)
    sd = ImageDraw.Draw(stage)
    sd.polygon(outer_quad, fill=(5, 5, 8, 255))
    sd.polygon(inner_quad, fill=(10, 38, 184, 255))

    # On partial rows, add a smooth dark-blue shadow vignette across the unoccupied right side (no stripes)
    start_x = 100
    card_y = bezel
    step = CARD_BODY_W + CARD_GAP
    if 0 < len(row) < COLUMNS:
        fade_start = start_x + len(row) * step - CARD_SKEW // 2 + 40
        fade = Image.new('RGBA', stage.size, (0, 0, 0, 0))
        fd = ImageDraw.Draw(fade)
        span = max(1, STAGE_W - fade_start)
        for x in range(max(0, int(fade_start)), STAGE_W, 4):
            t = min(1.0, max(0.0, (x - fade_start) / span))
            alpha = round(145 * (t ** 1.15))
            fd.rectangle((x, bezel, x + 4, stage_h - bezel), fill=(3, 8, 34, alpha))
        fade_mask = Image.new('L', stage.size, 0)
        ImageDraw.Draw(fade_mask).polygon(inner_quad, fill=255)
        stage.alpha_composite(Image.composite(fade, Image.new('RGBA', stage.size), fade_mask))

    for index, entry in enumerate(row):
        card = _team_card(renderer, entry, registry)
        layout_x = start_x + index * step
        stage.alpha_composite(card, (layout_x - CARD_SKEW // 2, card_y))

    # Crisp pure-black top & bottom bezel edges over card seams, matching the real game's thick black frame
    sd = ImageDraw.Draw(stage)
    sd.polygon([(0, 0), (STAGE_W, 0), (STAGE_W, bezel), (0, bezel)], fill=(5, 5, 8, 255))
    sd.polygon([(0, stage_h - bezel), (STAGE_W, stage_h - bezel), (STAGE_W - 28, stage_h), (0, stage_h)],
               fill=(5, 5, 8, 255))

    tilted = stage.rotate(4.2, resample=Image.Resampling.BICUBIC, expand=True)
    viewport.alpha_composite(tilted, ((VIEW_W - tilted.width) // 2, (VIEW_H - tilted.height) // 2))
    return viewport


def render_team(renderer, rows, registry, user_name, page, pages, character_count, weapon_count,
                remaining, avatar=None):
    images = ([_render_row(renderer, row, registry, idx) for idx, row in enumerate(rows)]
              if rows else [_team_background(renderer, (VIEW_W, VIEW_H))])
    height = HEADER_H + VIEW_H * len(images) + FOOTER_H
    stitched = _team_background(renderer, (VIEW_W, height)).convert('RGB')
    for index, image in enumerate(images):
        stitched.paste(image.convert('RGB'), (0, HEADER_H + index * VIEW_H))

    draw = ImageDraw.Draw(stitched)
    draw.polygon([(0, 0), (VIEW_W, 0), (VIEW_W, 128), (0, HEADER_H)], fill=(7, 10, 22))
    draw.polygon([(0, 144), (VIEW_W, 120), (VIEW_W, 129), (0, 153)], fill=(10, 38, 184))
    draw.text((48, 18), 'PHANTOM / COLLECTION', font=renderer.font(21, latin=True), fill=(139, 157, 255))
    draw.text((46, 48), '我的队伍 · 收藏名册', font=renderer.font(44), fill='white')
    draw.text((48, 104), f'角色 {character_count} 位  /  武器 {weapon_count} 件  ·  今日可抽 {remaining} 抽',
              font=renderer.font(23), fill=(200, 210, 245))

    right_text_x = VIEW_W - 48
    if avatar:
        try:
            with Image.open(io.BytesIO(avatar)) as src:
                face = ImageOps.fit(src.convert('RGBA'), (74, 74), Image.Resampling.LANCZOS)
            av_mask = Image.new('L', (74, 74), 0)
            ImageDraw.Draw(av_mask).polygon([(11, 0), (74, 0), (63, 74), (0, 74)], fill=255)
            ax, ay = VIEW_W - 122, 26
            draw.polygon([(ax + 11 - 3, ay - 3), (ax + 74 + 3, ay - 3),
                          (ax + 63 + 3, ay + 74 + 3), (ax - 3, ay + 74 + 3)], fill=(42, 86, 255))
            stitched.paste(face.convert('RGB'), (ax, ay), av_mask)
            right_text_x = VIEW_W - 140
        except Exception:
            pass

    draw.text((right_text_x, 22), f'{page:02d} / {pages:02d}', font=renderer.font(24, latin=True),
              anchor='ra', fill='white')
    name = ' '.join((user_name or '玩家').split())[:30]
    draw.text((right_text_x, 68), name, font=_fit_text(renderer, draw, name, 480, 26), anchor='ra', fill='white')

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

