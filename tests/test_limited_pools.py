"""Feature-level contracts for limited rosters, targeting, names and shared persistence."""
import sys
from pathlib import Path
from dataclasses import replace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.core.registry import Registry
from src.core.models import PityState
from src.core.mechanics import GachaMechanics
from src.core.store import Store
from src.services.gacha_service import GachaService
from src.render.roster import roster_pages,render_roster
from src.render.renderer import Renderer

@pytest.fixture
def registry():
    return Registry.load()

def test_complete_rosters_ignore_art_availability(registry):
    chars={i.id for i in registry.items.values() if i.id.startswith('char:') and i.rarity==5 and i.limited and i.id not in registry.excluded}
    assert {i.id for i in registry.banner('char_all_limited').candidates(5)}==chars
    assert 'char:SKULL·Starlight' not in chars
    assert 'char:SKULL·Starlight' in registry.items
    weapons={i.id for i in registry.items.values() if i.id.startswith('weapon:') and i.rarity==5 and 'char:'+i.id[7:].split('-weapon')[0] in chars}
    assert {i.id for i in registry.banner('weapon_all_limited').candidates(5)}==weapons
    for base,roster in [('char_all_limited',registry.limited_characters()),('weapon_all_limited',registry.limited_weapons())]:
        banner=registry.banner(base)
        for item in roster:
            target=registry.banner('target:'+item.id)
            assert target.pool==banner.pool
            assert target.pity_group==banner.pity_group
            assert target.rate_up[5]==(item,)
            assert not target.selector_at
            assert target.hard_pity==banner.hard_pity
        assert not banner.rate_up

def test_names_and_forms(registry):
    for name in ('哈姆子','P3P女主','KOTONE','Kotone Shiomi','汐見 琴音'):
        assert registry.resolve(name).id=='target:char:KOTONE'
    assert registry.resolve('鬼太郎').id=='target:char:MAKOTO'
    assert registry.resolve('周星驰').id=='target:char:JOKER·Starlight'
    assert registry.resolve('skull starlight') is None
    assert '下架' in registry.selection_error('星舞龙司')
    assert registry.resolve('瑤鈴・新春').id=='target:char:RIN·Firecracker'
    assert registry.resolve('鹿野莓').id=='target:char:BERRY'
    assert registry.resolve('夏日鹿野莓').id=='target:char:BERRY·Summer'
    assert registry.resolve('夏日') is None
    assert '歧义' in registry.selection_error('夏日')
    assert registry.resolve('雨宫莲') is None # cannot silently pick star form
    assert '限定' in registry.selection_error('雨宫莲')
    assert registry.resolve('不存在') is None

def test_configuration_and_weapon_resolution(registry):
    assert registry.configured_default({}).id=='char_all_limited'
    assert registry.configured_default({'default_banner':'char_limited'}).id=='char_all_limited'
    assert registry.configured_default({'default_pool_type':'weapon'}).id=='weapon_all_limited'
    assert registry.configured_default({'selected_character':'哈姆子'}).id=='target:char:KOTONE'
    weapon=registry.resolve('武器 哈姆子')
    assert weapon and weapon.pity_group=='weapon'
    assert registry.configured_default({'default_pool_type':'weapon','selected_weapon':'哈姆子'})==weapon
    assert registry.resolve(weapon.rate_up[5][0].name)==weapon
    for config in ({'selected_character':'夏日'},{'selected_character':'雨宫莲'},{'default_pool_type':'wrong'},{'default_banner':'typo'}):
        with pytest.raises(ValueError):registry.configured_default(config)

class HighRoll:
    def random(self):return .99
    def choice(self,seq):return seq[0]

class FirstFiveThenLow(HighRoll):
    def __init__(self):self.calls=0
    def random(self):
        self.calls+=1
        return 0 if self.calls==1 else .99

def test_shared_counts_pity_reset_and_persistence(registry,tmp_path):
    path=tmp_path/'state.db'; store=Store(path); service=GachaService(registry,store,daily_pulls=1000)
    base=registry.banner('char_all_limited'); target=registry.resolve('哈姆子'); another=registry.resolve('鬼太郎')
    service.mechanics=GachaMechanics(HighRoll())
    first=service.draw('qq','u',base,10)
    assert first.state.pity5==10
    second=service.draw('qq','u',target,10)
    assert second.state.pity5==20 and second.state.pulls==20
    assert service.state_of('qq','u',another)==second.state
    store.save_state('qq','u',base.pity_group,replace(second.state,guaranteed5=True))
    service.mechanics=GachaMechanics(FirstFiveThenLow())
    third=service.draw('qq','u',target,10)
    assert third.results[0].rarity==5 and third.results[0].item.id=='char:KOTONE'
    assert third.state.pity5==9 and third.state.pulls==30 and not third.state.guaranteed5
    service.mechanics=GachaMechanics(HighRoll())
    service.draw('qq','u',registry.banner('weapon_all_limited'),10)
    assert service.state_of('qq','u',another).pulls==30
    assert store.total_pulls('qq','u')==40
    store.close(); store=Store(path)
    assert store.load_state('qq','u',base.pity_group).pity5==9
    assert store.load_state('qq','u',base.pity_group).pulls==30
    store.close()

def test_all_pool_preserves_saved_up_guarantee(registry):
    base=registry.banner('char_all_limited')
    results,state=GachaMechanics(FirstFiveThenLow()).pull_many(base,PityState(guaranteed5=True),1)
    assert results[0].rarity==5 and state.pity5==0 and state.guaranteed5
    results,state=GachaMechanics(FirstFiveThenLow()).pull_many(registry.resolve('哈姆子'),state,1)
    assert results[0].is_up and not state.guaranteed5

def test_roster_pages_include_everyone(registry):
    roster=registry.limited_characters(); pages=roster_pages(roster)
    assert tuple(i for page in pages for i in page)==roster
    assert all(1<=len(p)<=12 for p in pages)
    image=render_roster(Renderer(),pages[-1],len(pages),len(pages),'当前：汐见琴音·角色池',{'char:KOTONE'},36)
    assert image.size==(1440,660)


def test_missed_up_guarantee_is_shared_between_targets(registry,tmp_path):
    class MissUp(HighRoll):
        def __init__(self):self.calls=0
        def random(self):
            self.calls+=1
            return 0 if self.calls==1 else .99
    store=Store(tmp_path/'shared.db'); service=GachaService(registry,store,daily_pulls=1000)
    first=registry.resolve('哈姆子'); second=registry.resolve('鬼太郎')
    service.mechanics=GachaMechanics(MissUp())
    missed=service.draw('qq','u',first,1)
    assert missed.results[0].rarity==5 and not missed.results[0].is_up
    assert missed.state.guaranteed5
    service.mechanics=GachaMechanics(FirstFiveThenLow())
    got=service.draw('qq','u',second,1)
    assert got.results[0].item.id=='char:MAKOTO' and got.results[0].is_up
    assert got.state.pulls==2 and not got.state.guaranteed5
    store.close()

@pytest.mark.parametrize('pool,hard',[('char_all_limited',80),('weapon_all_limited',70)])
def test_hard_pity_rules_are_inherited(registry,pool,hard):
    banner=registry.banner(pool)
    results,state=GachaMechanics(HighRoll()).pull_many(banner,PityState(pity5=hard-1),1)
    assert results[0].rarity==5 and state.pity5==0
    assert results[0].item in banner.candidates(5)


def test_star_ryuji_removed_from_all_pools_and_can_be_restored(registry,tmp_path):
    import shutil,json
    excluded='char:SKULL·Starlight'
    assert len(registry.limited_characters())==37
    assert registry.resolve(excluded) is None
    assert registry.resolve('target:'+excluded) is None
    for banner in registry.enabled_banners():
        assert all(item.id!=excluded for pool in banner.pool.values() for item in pool)
        assert all(item.id!=excluded for pool in banner.rate_up.values() for item in pool)
    source=Path(__file__).resolve().parents[1]/'data'
    shutil.copytree(source,tmp_path/'data')
    (tmp_path/'data/excluded_characters.json').write_text('[]',encoding='utf-8')
    restored=Registry.load(tmp_path/'data')
    assert len(restored.limited_characters())==38
    assert restored.resolve('星舞龙司').id=='target:'+excluded
