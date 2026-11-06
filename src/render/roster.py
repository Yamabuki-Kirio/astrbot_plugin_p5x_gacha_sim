"""限定角色卡面目录，支持将全部角色排成一张长图。"""
from PIL import Image, ImageDraw

PAGE_SIZE = 12


def roster_pages(items):
    return [tuple(items[n:n+PAGE_SIZE]) for n in range(0, len(items), PAGE_SIZE)]


def _fit_text(renderer, draw, text, width, size):
    while size > 14 and draw.textlength(text, font=renderer.font(size)) > width:
        size -= 1
    return renderer.font(size)


def _portrait(renderer, item, size):
    pair = renderer._character_pair(item)
    if pair:
        art = renderer._source_art(pair[0]).copy()
        bounds = art.getchannel('A').getbbox()
        if bounds:
            art = art.crop(bounds)
        placement = renderer._placement(item) or {'face':[.5,.15], 'face_width':.20}
        fx,fy = placement['face']
        factor = size[0]*.43 / (art.width*placement['face_width'])
        # Frame the calibrated face and upper body, keeping the face below the number ribbon.
        left = fx*art.width-size[0]*.5/factor
        top = fy*art.height-size[1]*.33/factor
        return art.transform(size, Image.Transform.AFFINE,
            (1/factor,0,left,0,1/factor,top), Image.Resampling.BICUBIC)
    art = renderer.portrait(item)
    if art:
        from PIL import ImageOps
        return ImageOps.contain(art, size, Image.Resampling.LANCZOS)
    return None


def render_roster(renderer, items, page, pages, status, up_ids=(), offset=0):
    height = 335 + 325 * max(1, (len(items)+3)//4)
    canvas = renderer._background((1440,height))
    draw = ImageDraw.Draw(canvas)
    draw.polygon([(0,0),(1440,0),(1440,180),(0,220)],fill=(7,10,22,245))
    draw.polygon([(0,199),(1440,158),(1440,170),(0,211)],fill=(33,66,245))
    draw.text((48,26),'PHANTOM CONTRACT',font=renderer.font(24,latin=True),fill=(134,151,255))
    draw.text((45,62),'限定怪盗 · 契约名册',font=renderer.font(49),fill='white')
    draw.text((48,129), status, font=_fit_text(renderer,draw,status,1220,25), fill=(239,209,255))
    draw.text((1388,45),f'{len(items)} 位限定' if pages == 1 else f'{page:02d} / {pages:02d}',font=renderer.font(27),anchor='ra',fill='white')
    for n,item in enumerate(items):
        col,row=n%4,n//4
        x,y=48+col*344,239+row*325
        w,h=312,302
        selected=item.id in up_ids
        card=Image.new('RGBA',(w,h),(0,0,0,0)); cd=ImageDraw.Draw(card)
        cd.polygon([(15,0),(w,0),(w-15,h),(0,h)],fill=(18,22,48),outline=(193,115,255) if selected else (78,88,137),width=3)
        cd.polygon([(16,3),(w-4,3),(w-15,218),(5,232)],fill=(53,44,98) if selected else (24,31,65))
        for line in range(0,340,34):
            cd.line([(line,3),(line-90,224)],fill=(44,49,94),width=1)
        art=_portrait(renderer,item,(w-20,230))
        if art:
            card.alpha_composite(art,((w-art.width)//2,0))
        else:
            cd.text((w//2,110),'立绘待补',font=renderer.font(26),anchor='mm',fill=(161,168,193))
        # A fixed opaque label keeps names readable over every illustration.
        cd.polygon([(7,226),(w-13,216),(w-17,h-4),(3,h-4)],fill=(7,10,23))
        cd.text((18,236),item.name,font=_fit_text(renderer,cd,item.name,w-39,23),fill='white')
        cd.text((18,272),item.id.partition(':')[2],font=_fit_text(renderer,cd,item.id.partition(':')[2],w-39,17),fill=(153,166,244))
        cd.polygon([(15,0),(85,0),(76,33),(13,33)],fill=(37,65,223))
        cd.text((25,3),f'{offset+n+1:02d}',font=renderer.font(22,latin=True),fill='white')
        if selected:
            cd.polygon([(w-84,0),(w,0),(w-4,34),(w-91,34)],fill=(193,115,255))
            cd.text((w-50,2),'UP',font=renderer.font(24,latin=True),anchor='ma',fill=(10,8,20))
        canvas.alpha_composite(card,(x,y))
    draw=ImageDraw.Draw(canvas)
    draw.line([(48,height-68),(1392,height-68)],fill=(69,90,250),width=3)
    draw.text((48,height-49),'/十连 角色名或别名  ·  /p5x 选择 编号  ·  /签到',font=renderer.font(23),fill='white')
    draw.text((1390,height-45),'五星仅限限定怪盗',font=renderer.font(20),anchor='ra',fill=(159,169,219))
    return canvas.convert('RGB')
