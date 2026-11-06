"""AstrBot entry points tested with a minimal API adapter, without a live QQ account."""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]

class Filters:
    def command(self,*args,**kwargs):
        return lambda f:f
    def command_group(self,*args,**kwargs):
        def decorate(f):
            f.command=self.command
            return f
        return decorate

class Event:
    def __init__(self,message=''):self.message_str=message
    def get_message_str(self):return self.message_str
    def get_platform_id(self):return 'qq'
    def get_sender_id(self):return '123'
    def get_sender_name(self):return '玩家'
    def plain_result(self,text):return text
    def chain_result(self,chain):return chain

@pytest.fixture
def plugin(monkeypatch,tmp_path):
    filters=Filters()
    for name in ('astrbot','astrbot.api','astrbot.api.event','astrbot.api.star','astrbot.core','astrbot.core.message','astrbot.core.message.components'):
        monkeypatch.setitem(sys.modules,name,types.ModuleType(name))
    api=sys.modules['astrbot.api']; api.AstrBotConfig=dict
    api.logger=types.SimpleNamespace(exception=lambda *a:None,error=lambda *a:None,info=lambda *a:None)
    sys.modules['astrbot.api.event'].AstrMessageEvent=Event
    sys.modules['astrbot.api.event'].filter=filters
    star=sys.modules['astrbot.api.star']; star.Context=object
    class Star:
        def __init__(self,context):pass
    star.Star=Star; star.StarTools=types.SimpleNamespace(get_data_dir=lambda *a:tmp_path)
    sys.modules['astrbot.core.message.components'].Image=types.SimpleNamespace(fromBytes=lambda b:b)
    pkg=types.ModuleType('gacha_feature_test'); pkg.__path__=[str(ROOT)]
    monkeypatch.setitem(sys.modules,'gacha_feature_test',pkg)
    spec=importlib.util.spec_from_file_location('gacha_feature_test.main',ROOT/'main.py')
    module=importlib.util.module_from_spec(spec); monkeypatch.setitem(sys.modules,spec.name,module); spec.loader.exec_module(module)
    instance=module.P5XGachaPlugin(None,{'enable_rendering':False, 'daily_draw_limit':1000})
    instance._setup(); assert not instance._init_error
    yield instance
    instance.store.close()

async def collect(generator):return [r async for r in generator]

def run(generator):return asyncio.run(collect(generator))

def test_standalone_default_and_named_ten(plugin):
    result=run(plugin.direct_ten(Event('/十连')))
    assert '全限定角色池' in result[0]
    result=run(plugin.direct_ten(Event('/十连 Kotone Shiomi'),'Kotone'))
    assert '汐见琴音·角色池' in result[0]
    state=plugin.service.state_of('qq','123',plugin.registry.resolve('鬼太郎'))
    assert state.pulls==20
    result=run(plugin.direct_ten(Event('/十连 武器 哈姆子'),'武器'))
    assert '武器池' in result[0]
    assert plugin.service.state_of('qq','123',plugin.registry.banner('weapon_all_limited')).pulls==10
    assert plugin.service.state_of('qq','123',plugin.registry.banner('char_all_limited')).pulls==20

def test_defaults_config_personal_explicit_precedence(plugin):
    plugin.config['selected_character']='鬼太郎'
    assert plugin._resolve(Event(),'').id=='target:char:MAKOTO'
    run(plugin.cmd_select(Event('/p5x 选择 哈姆子'),'哈姆子'))
    assert plugin._resolve(Event(),'').id=='target:char:KOTONE'
    assert plugin._resolve(Event(),'鬼太郎').id=='target:char:MAKOTO'
    run(plugin.cmd_select(Event('/p5x 选择 全角色池'),'全角色池'))
    assert plugin._resolve(Event(),'').id=='char_all_limited'

def test_roster_text_and_image_paths(plugin,monkeypatch):
    output=run(plugin.direct_banners(Event('/卡池')))
    assert len(output)==1 and '无单独UP' in output[0]
    for item in plugin.registry.limited_characters():
        assert item.name in output[0]
    plugin.config['enable_rendering']=True
    plugin.config['selected_character']='哈姆子'
    output=run(plugin.direct_banners(Event('/卡池')))
    assert len(output)==1 and len(output[0])==1
    assert isinstance(output[0][0],bytes)
    from PIL import Image
    import io
    with Image.open(io.BytesIO(output[0][0])) as image:
        assert image.size==(1440,3585)


def test_bad_and_ambiguous_input_do_not_draw(plugin):
    for target in ('不存在','夏日','雨宫莲'):
        result=run(plugin.direct_ten(Event('/十连 '+target),target))
        assert '没有找到' in result[0] or '歧义' in result[0] or '限定' in result[0]
    assert plugin.store.total_pulls('qq','123')==0
    plugin.config['selected_character']='typo'
    assert '配置错误' in run(plugin.direct_ten(Event('/十连')))[0]
    assert plugin.store.total_pulls('qq','123')==0

def test_pity_and_number_selection(plugin):
    result=run(plugin.cmd_select(Event('/p5x 选择 1'),'1'))
    assert plugin.registry.limited_characters()[0].name in result[0]
    run(plugin.direct_ten(Event('/十连')))
    result=run(plugin.cmd_pity(Event('/p5x 保底 哈姆子'),'哈姆子'))
    assert '共享累计 10 抽' in result[0]


def test_daily_default_signin_and_quota_commands(plugin):
    plugin.service.daily_pulls=10
    event=Event('/十连')
    assert '剩余 10 抽' in run(plugin.direct_quota(event))[0]
    assert '剩余 0 抽' in run(plugin.direct_ten(event))[0]
    assert '抽卡失败' in run(plugin.direct_ten(event))[0]
    assert plugin.store.total_pulls('qq','123')==10
    message=run(plugin.direct_signin(Event('/签到')))[0]
    assert '获得 10 抽' in message and '剩余 10 抽' in message
    assert '不可重复' in run(plugin.direct_signin(Event('/签到')))[0]
    assert '已签到' in run(plugin.direct_quota(event))[0]
    assert '剩余 0 抽' in run(plugin.direct_ten(event))[0]
    assert plugin.store.total_pulls('qq','123')==20
    assert '抽卡失败' in run(plugin.cmd_single(Event('/p5x 单抽')))[0]


def test_daily_remaining_forwarded_to_image_footer(plugin,monkeypatch):
    plugin.service.daily_pulls=10
    plugin.config['enable_rendering']=True
    monkeypatch.setattr(sys.modules[plugin.__class__.__module__], 'avatar_bytes', lambda e:None)
    captured={}
    async def render(factory):
        factory()
        return ['image']
    monkeypatch.setattr(plugin,'_render',render)
    def ten(*a,**kw):captured.update(kw)
    monkeypatch.setattr(plugin.renderer,'render_ten',ten)
    assert run(plugin.direct_ten(Event('/十连')))==[['image']]
    assert '今日剩余0抽' in captured['footer']


def test_refresh_requires_explicit_whitelist(plugin,monkeypatch):
    plugin.service.daily_pulls=10
    event=Event('/刷新')
    monkeypatch.setattr(event,'is_admin',lambda:True,raising=False)
    before=plugin.service.quota_of('qq','123')
    assert '权限不足' in run(plugin.direct_refresh(event))[0]
    assert plugin.service.quota_of('qq','123')==before
    plugin.config['admin_whitelist']=['other']
    assert '权限不足' in run(plugin.cmd_refresh(event))[0]
    plugin.config['admin_whitelist']='123'
    assert '权限不足' in run(plugin.direct_refresh(event))[0]
    plugin.config['admin_whitelist']=[' 123 ']
    assert '刷新完成' in run(plugin.direct_refresh(event))[0]
    assert plugin.service.quota_of('qq','123').remaining==20
    plugin.config['admin_whitelist']=[123]
    assert '刷新完成' in run(plugin.cmd_refresh(event))[0]
    assert plugin.service.quota_of('qq','123').remaining==30


def test_downlisted_character_is_not_drawn_or_listed(plugin):
    assert '下架' in run(plugin.direct_ten(Event('/十连 星舞龙司'),'星舞龙司'))[0]
    output=run(plugin.direct_banners(Event('/卡池')))
    assert '坂本龙司·星舞' not in output[0]
    assert plugin.store.total_pulls('qq','123')==0


def test_signin_after_admin_refresh_keeps_both_rewards(plugin):
    plugin.service.daily_pulls=10
    plugin.service.quota_of('qq','123')
    plugin.config['admin_whitelist']=['123']
    run(plugin.direct_refresh(Event('/刷新')))
    message=run(plugin.direct_signin(Event('/签到')))[0]
    assert '获得 10 抽' in message and '剩余 30 抽' in message
    assert '额外获得 20 抽' in run(plugin.direct_quota(Event('/抽卡次数')))[0]


def test_team_command_empty_text_image_and_page_validation(plugin,monkeypatch):
    event=Event('/队伍')
    assert '尚未获得' in run(plugin.direct_team(event))[0]
    assert '页码范围' in run(plugin.direct_team(event,'2'))[0]
    plugin.config['enable_rendering']=True
    monkeypatch.setattr(sys.modules[plugin.__class__.__module__],'avatar_bytes',lambda e:None)
    images=run(plugin.direct_team(event))
    assert len(images)==1 and len(images[0])==1
    from PIL import Image
    import io
    with Image.open(io.BytesIO(images[0][0])) as image:assert image.size==(1440,740)


def test_team_command_lists_every_owned_card_and_keeps_groups(plugin,monkeypatch):
    for item in plugin.registry.items.values():
        if item.id.startswith(('char:','weapon:')) and item.rarity in (4,5):
            plugin.store.add_owned('qq','123',item)
    text=run(plugin.direct_team(Event('/队伍')))
    owned=plugin.service.team_of('qq','123')
    for entry in owned:assert any(entry.item.name in page for page in text)
    assert len(text)>1
    assert len(run(plugin.direct_team(Event('/队伍 2'),'2')))==1
    plugin.config['enable_rendering']=True
    monkeypatch.setattr(sys.modules[plugin.__class__.__module__],'avatar_bytes',lambda e:None)
    captured=[]
    def render(renderer, rows, registry, user_name, page, pages, *a):
        captured.append((rows,page,pages))
    monkeypatch.setattr(sys.modules[plugin.__class__.__module__],'render_team',render)
    async def image(factory):factory(); return ['image']
    monkeypatch.setattr(plugin,'_render',image)
    result=run(plugin.cmd_team(Event('/p5x 队伍')))
    assert len(result)==len(captured)
    assert sum(len(row) for rows,_,_ in captured for row in rows)==len(owned)


def test_overflow_notice_and_remaining_in_image_path(plugin,monkeypatch):
    item=plugin.registry.item('char:KOTONE')
    for _ in range(7):plugin.store.add_owned('qq','123',item)
    from src.core.mechanics import PullResult
    from dataclasses import replace
    def pull(banner,state,count):
        return [PullResult(item,5,True,n+1,0,0) for n in range(count)],replace(state,pulls=state.pulls+count)
    monkeypatch.setattr(plugin.service.mechanics,'pull_many',pull)
    plugin.service.daily_pulls=10
    plugin.config['enable_rendering']=True
    monkeypatch.setattr(sys.modules[plugin.__class__.__module__],'avatar_bytes',lambda e:None)
    captured={}
    monkeypatch.setattr(plugin.renderer,'render_ten',lambda *a,**kw:captured.update(kw))
    async def image(factory):factory(); return ['image']
    monkeypatch.setattr(plugin,'_render',image)
    result=run(plugin.direct_ten(Event('/十连')))
    assert result[0]==['image']
    assert '返还 100 抽' in result[1] and '剩余 100 抽' in result[1]
    assert '今日剩余100抽' in captured['footer']


def test_pool_help_serves_bundled_image_without_rendering_or_database(plugin):
    module = sys.modules[type(plugin).__module__]
    expected = module.TUTORIAL_IMAGE.read_bytes()
    plugin.service = None
    plugin.registry = None
    plugin.renderer = None
    for handler in (plugin.direct_pool_help, plugin.cmd_pool_help):
        assert run(handler(Event('/卡池帮助'))) == [[expected]]
    assert expected.startswith(b'\xff\xd8')


def test_pool_help_missing_asset_falls_back_to_commands(plugin, monkeypatch, tmp_path):
    module = sys.modules[type(plugin).__module__]
    monkeypatch.setattr(module, 'TUTORIAL_IMAGE', tmp_path / 'missing.jpg')
    output = run(plugin.direct_pool_help(Event('/卡池帮助')))
    assert len(output) == 1
    assert '教程图片暂时不可用' in output[0]
    assert '/签到' in output[0] and '/队伍' in output[0]
