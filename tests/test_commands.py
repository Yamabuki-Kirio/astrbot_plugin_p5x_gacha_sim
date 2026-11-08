"""AstrBot entry points tested with a minimal API adapter, without a live QQ account."""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]

class Filters:
    def event_message_type(self,*args,**kwargs):
        return lambda f:f
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
    def stop_event(self):self.stopped=True
    def get_platform_id(self):return 'qq'
    def get_sender_id(self):return '123'
    def get_sender_name(self):return '玩家'
    def plain_result(self,text):return text
    def chain_result(self,chain):return chain

@pytest.fixture
def plugin(monkeypatch,tmp_path):
    filters=Filters()
    for name in ('astrbot','astrbot.api','astrbot.api.event','astrbot.api.event.filter','astrbot.api.star','astrbot.core','astrbot.core.message','astrbot.core.message.components'):
        monkeypatch.setitem(sys.modules,name,types.ModuleType(name))
    api=sys.modules['astrbot.api']; api.AstrBotConfig=dict
    api.logger=types.SimpleNamespace(exception=lambda *a:None,error=lambda *a:None,info=lambda *a:None)
    sys.modules['astrbot.api.event'].AstrMessageEvent=Event
    sys.modules['astrbot.api.event'].filter=filters
    sys.modules['astrbot.api.event.filter'].EventMessageType=types.SimpleNamespace(ALL=object())
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


def test_bare_ten_ignores_saved_and_configured_target(plugin):
    plugin.config['selected_character'] = '鬼太郎'
    run(plugin.cmd_select(Event('/p5x 选择 哈姆子'), '哈姆子'))
    assert '全限定角色池' in run(plugin.direct_ten(Event('/十连')))[0]
    assert '汐见琴音·角色池' in run(plugin.direct_ten(Event('/十连 哈姆子'), '哈姆子'))[0]
    assert '全限定角色池' in run(plugin.direct_ten(Event('/十连')))[0]

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
    assert '全限定角色池' in run(plugin.direct_ten(Event('/十连')))[0]
    assert plugin.store.total_pulls('qq','123')==10

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


def test_plain_commands_default_off_and_unrelated_messages(plugin):
    assert run(plugin.handle_plain_commands(Event('十连'))) == []
    plugin.config['enable_plain_commands'] = True
    for text in ('', '/十连', '我想十连', '十连抽', '卡池帮助一下', '签到 明天'):
        event = Event(text)
        assert run(plugin.handle_plain_commands(event)) == []
        assert not getattr(event, 'stopped', False)
    assert plugin.store.total_pulls('qq', '123') == 0


def test_plain_commands_draw_once_and_preserve_target(plugin):
    plugin.config['enable_plain_commands'] = True
    for text, expected in [('十连', '全限定角色池'), ('十连 哈姆子', '汐见琴音'),
                           ('p5x 十连 鬼太郎', '结城理'), ('十连 武器池', '武器池')]:
        event = Event(text)
        output = run(plugin.handle_plain_commands(event))
        assert expected in output[0]
        assert event.stopped
    assert plugin.store.total_pulls('qq', '123') == 40


def test_plain_signin_quota_help_team_and_admin(plugin):
    plugin.config['enable_plain_commands'] = True
    assert '签到成功' in run(plugin.handle_plain_commands(Event('签到')))[0]
    assert '不可重复' in run(plugin.handle_plain_commands(Event('p5x签到')))[0]
    assert '剩余' in run(plugin.handle_plain_commands(Event('抽卡次数')))[0]
    assert '队伍' in run(plugin.handle_plain_commands(Event('队伍')))[0]
    assert '页码范围' in run(plugin.handle_plain_commands(Event('队伍 2')))[0]
    assert isinstance(run(plugin.handle_plain_commands(Event('卡池帮助')))[0][0], bytes)
    assert '权限不足' in run(plugin.handle_plain_commands(Event('刷新')))[0]
    plugin.config['admin_whitelist'] = ['123']
    assert '刷新完成' in run(plugin.handle_plain_commands(Event('p5x 刷新')))[0]
    plugin.config['enable_plain_commands'] = False
    assert run(plugin.handle_plain_commands(Event('十连'))) == []


@pytest.mark.parametrize('count,method,label', [(20,'direct_twenty','二十连'),(30,'direct_thirty','三十连'),(40,'direct_forty','四十连')])
def test_multi_draw_command_counts_and_exact_plain_match(plugin,count,method,label):
    event=Event('/'+label+' 哈姆子')
    output=run(getattr(plugin,method)(event,'哈姆子'))
    assert len(output)==1 and '汐见琴音' in output[0]
    assert sum(bool(__import__('re').match(r'\s*\d+\.', line)) for line in output[0].splitlines())==count
    assert plugin.store.total_pulls('qq','123')==count
    plugin.config['enable_plain_commands']=True
    assert run(plugin.handle_plain_commands(Event('想'+label)))==[]
    assert run(plugin.handle_plain_commands(Event(label+'哈姆子')))==[]
    assert '结城理' in run(plugin.handle_plain_commands(Event(label+' 鬼太郎')))[0]
    assert plugin.store.total_pulls('qq','123')==count*2


def test_multi_draw_rejects_insufficient_budget_as_one_operation(plugin):
    plugin.service.daily_pulls=20
    result=run(plugin.direct_forty(Event('/四十连')))
    assert len(result)==1 and '本次需要 40 抽' in result[0]
    assert plugin.store.total_pulls('qq','123')==0
    assert plugin.service.quota_of('qq','123').remaining==20


def test_multi_draw_render_single_composite_and_fallback_without_redraw(plugin,monkeypatch):
    import io
    from PIL import Image
    plugin.config['enable_rendering']=True
    module=sys.modules[type(plugin).__module__]
    monkeypatch.setattr(module,'avatar_bytes',lambda event:None)
    original=plugin.renderer.render_ten
    calls=[]
    def render(results,banner,**kwargs):
        calls.append((len(results),kwargs))
        return original(results,banner,**kwargs)
    monkeypatch.setattr(plugin.renderer,'render_ten',render)
    output=run(plugin.direct_thirty(Event('/三十连 武器池'),'武器池'))
    assert len(output)==1 and len(output[0])==1
    with Image.open(io.BytesIO(output[0][0])) as image:
        assert image.size==(1920,80+873*3)
    assert [n for n,_ in calls]==[10,10,10]
    assert calls[0][1]['batch_label'].startswith('第1/3组')
    assert all('当前 ' in kw['footer'] for _,kw in calls)
    assert plugin.store.total_pulls('qq','123')==30
    def fail(*args,**kwargs):raise RuntimeError('render failure')
    monkeypatch.setattr(plugin.renderer,'render_ten',fail)
    output=run(plugin.direct_twenty(Event('/二十连')))
    assert len(output)==1 and '二十连结果' in output[0]
    assert plugin.store.total_pulls('qq','123')==50

@pytest.mark.parametrize('command', ['/抽卡 哈姆子','抽卡 哈姆子','p5x 抽卡 哈姆子'])
def test_draw_all_direct_and_plain_remaining(plugin,command):
    plugin.service.daily_pulls=17
    plugin.config['enable_plain_commands']=True
    event=Event(command)
    output=run(plugin.direct_draw_all(event,'哈姆子')) if command.startswith('/') else run(plugin.handle_plain_commands(event))
    assert len(output)==1 and '汐见琴音' in output[0]
    assert plugin.store.total_pulls('qq','123')==17
    assert plugin.service.quota_of('qq','123').remaining==0
    assert '剩余 0 抽' in run(plugin.direct_draw_all(Event('/抽卡')))[0]
    assert plugin.store.total_pulls('qq','123')==17


def test_draw_all_split_images_and_partial_last_row(plugin,monkeypatch):
    import io
    from PIL import Image
    plugin.service.daily_pulls=57
    plugin.config['enable_rendering']=True
    module=sys.modules[type(plugin).__module__]
    monkeypatch.setattr(module,'avatar_bytes',lambda event:None)
    output=run(plugin.direct_draw_all(Event('/抽卡')))
    assert len(output)==2
    for result,rows in zip(output,[4,2]):
        with Image.open(io.BytesIO(result[0])) as image:
            assert image.size==(1920,80+873*rows)
    assert plugin.store.total_pulls('qq','123')==57
    assert plugin.service.quota_of('qq','123').remaining==0
    plugin.config['enable_plain_commands']=False
    assert run(plugin.handle_plain_commands(Event('抽卡')))==[]
