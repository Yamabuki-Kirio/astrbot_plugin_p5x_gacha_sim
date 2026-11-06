"""Team collection posters with adjacent owner/weapon groups and capped progress."""
from collections import defaultdict
import io
import math
from PIL import Image, ImageDraw, ImageOps, ImageFilter
from .roster import _portrait, _fit_text

COLUMNS = 4
ROWS_PER_PAGE = 4


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
        if row and len(row)+len(group)>COLUMNS:
            rows.append(tuple(row)); row=[]
        while len(group)>COLUMNS:
            rows.append(tuple(group[:COLUMNS])); group=group[COLUMNS:]
        row.extend(group)
        if len(row)==COLUMNS:
            rows.append(tuple(row)); row=[]
    if row: rows.append(tuple(row))
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


def _team_card(renderer, entry, registry):
    w,h=312,356; item=entry.item
    color=(193,115,255) if item.rarity==5 else (255,206,76)
    edge=(255,222,117) if entry.maxed else color
    card=Image.new('RGBA',(w,h)); d=ImageDraw.Draw(card)
    quad=[(14,0),(w,0),(w-14,h-1),(0,h-1)]
    d.polygon(quad,fill=(19,24,51),outline=(*edge,220),width=3)
    for x in range(0,w+100,30):d.line([(x,2),(x-90,229)],fill=(40,47,87),width=1)
    if item.id.startswith('char:'):
        art=_portrait(renderer,item,(w-20,220))
        if art:card.alpha_composite(art,((w-art.width)//2,4))
    else:
        art=renderer.portrait(item)
        if art:
            art=ImageOps.contain(art,(250,178),Image.Resampling.LANCZOS)
            card.alpha_composite(art,((w-art.width)//2,40+(178-art.height)//2))
    if art is None:
        d.text((w//2,118),'立绘待补',font=renderer.font(25),anchor='mm',fill=(153,163,194))
    if entry.maxed:
        # Static illustration of a gold sheen and star flashes, clipped inside the card.
        glow=Image.new('RGBA',card.size); gd=ImageDraw.Draw(glow)
        gd.polygon([(45,0),(83,0),(w-20,225),(w-58,225)],fill=(255,240,166,45))
        gd.line(quad+[quad[0]],fill=(255,229,133,180),width=8)
        mask=Image.new('L',card.size); ImageDraw.Draw(mask).polygon(quad,fill=255)
        glow=Image.composite(glow,Image.new('RGBA',card.size),mask)
        card.alpha_composite(glow.filter(ImageFilter.GaussianBlur(2)))
        d=ImageDraw.Draw(card)
        d.line(quad+[quad[0]],fill=(255,227,130),width=3)
        for x,y,rad in ((w-32,38,18),(22,193,13),(w-36,214,10)):
            _spark(d,x,y,rad,(255,250,225))
    d.polygon([(7,228),(w-10,218),(w-15,h-3),(2,h-3)],fill=(6,9,21))
    d.text((18,237),item.name,font=_fit_text(renderer,d,item.name,w-37,22),fill='white')
    owner=registry.item(entry.owner)
    detail=item.id[5:] if item.id.startswith('char:') else '专属 · '+(owner.name if owner else entry.owner[5:])
    d.text((18,269),detail,font=_fit_text(renderer,d,detail,w-37,16),fill=(157,171,220))
    d.text((18,299),entry.label,font=renderer.font(21),fill=(205,213,234))
    d.text((w-25,294),f'{entry.level}/6',font=renderer.font(29,latin=True),anchor='ra',fill=edge)
    for n in range(6):
        x=20+n*42
        d.polygon([(x,337),(x+32,337),(x+30,343),(x-2,343)],fill=edge if n<entry.level else (48,56,79))
    d.polygon([(14,0),(104,0),(96,32),(12,32)],fill=(*color,255))
    d.text((26,3),f'{item.rarity}★ '+('角色' if item.id.startswith('char:') else '武器'),font=renderer.font(17),fill=(11,11,24))
    if entry.maxed:
        d.polygon([(w-94,0),(w,0),(w-4,29),(w-100,29)],fill=(255,224,126))
        d.text((w-51,1),'MAX',font=renderer.font(21,latin=True),anchor='ma',fill=(20,16,10))
    return card


def render_team(renderer, rows, registry, user_name, page, pages, character_count, weapon_count,
                remaining, avatar=None):
    height=350+390*max(1,len(rows))
    canvas=renderer._background((1440,height)); d=ImageDraw.Draw(canvas)
    d.polygon([(0,0),(1440,0),(1440,183),(0,218)],fill=(7,10,22))
    d.polygon([(0,204),(1440,166),(1440,178),(0,216)],fill=(37,65,245))
    d.text((48,23),'PHANTOM / COLLECTION',font=renderer.font(23,latin=True),fill=(139,157,255))
    d.text((46,61),'我的队伍 · 收藏名册',font=renderer.font(47),fill='white')
    d.text((48,128),f'角色 {character_count} 位  /  武器 {weapon_count} 件  ·  今日可抽 {remaining} 抽',font=renderer.font(25),fill=(200,210,245))
    d.text((1388,28),f'{page:02d} / {pages:02d}',font=renderer.font(25,latin=True),anchor='ra',fill='white')
    name=' '.join((user_name or '玩家').split())[:30]
    d.text((1302,82),name,font=_fit_text(renderer,d,name,500,27),anchor='ra',fill='white')
    if avatar:
        try:
            with Image.open(io.BytesIO(avatar)) as source:
                face=ImageOps.fit(source.convert('RGBA'),(66,66),Image.Resampling.LANCZOS)
            mask=Image.new('L',(66,66)); ImageDraw.Draw(mask).polygon([(8,0),(65,0),(58,65),(0,65)],fill=255)
            canvas.paste(face,(1325,77),mask)
        except (OSError,ValueError):pass
    for yindex,row in enumerate(rows):
        for xindex,entry in enumerate(row):
            x,y=48+xindex*344,247+yindex*390
            if xindex and row[xindex-1].owner==entry.owner:
                d.line([(x-32,y+181),(x,y+181)],fill=(108,134,250),width=5)
            canvas.alpha_composite(_team_card(renderer,entry,registry),(x,y))
    d=ImageDraw.Draw(canvas)
    if not rows:
        d.text((720,390),'尚未获得四、五星角色或武器',font=renderer.font(35),anchor='mm',fill='white')
        d.text((720,455),'发送 /十连 开始收集你的队伍',font=renderer.font(25),anchor='mm',fill=(157,173,235))
    d.line([(48,height-68),(1392,height-68)],fill=(51,83,245),width=3)
    d.text((48,height-48),'首次 0/6 · 第七次 6/6 · 满阶重复返还10抽',font=renderer.font(22),fill='white')
    d.text((1390,height-47),'/队伍 页码' if pages>1 else '意识 / 进化',font=renderer.font(21),anchor='ra',fill=(165,178,232))
    return canvas.convert('RGB')
