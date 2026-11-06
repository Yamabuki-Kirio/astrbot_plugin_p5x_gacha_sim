"""Collection stages, filtered history, rewards, migrations and adjacent card grouping."""
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.core.registry import Registry
from src.core.models import PityState,Item
from src.core.mechanics import PullResult
from src.core.store import Store
from src.core.collection import collectible,OwnedItem
from src.services.gacha_service import GachaService
from src.render.team import team_rows,team_pages,render_team
from src.render.renderer import Renderer

class FixedResults:
    def __init__(self,items):self.items=items
    def pull_many(self,banner,state,count):
        items=[self.items[n%len(self.items)] for n in range(count)]
        return [PullResult(i,i.rarity,False,n+1,0,0) for n,i in enumerate(items)], replace(
            state,pulls=state.pulls+count,totals={**state.totals,banner.id:state.total_of(banner.id)+count})

@pytest.fixture
def env(tmp_path):
    r=Registry.load(); store=Store(tmp_path/'team.db'); service=GachaService(r,store)
    yield r,store,service
    store.close()

@pytest.mark.parametrize('prefix,rarity',[('char:',4),('char:',5),('weapon:',4),('weapon:',5)])
def test_first_seven_copies_and_only_excess_reward(env,prefix,rarity):
    r,store,s=env; item=next(i for i in r.items.values() if i.id.startswith(prefix) and i.rarity==rarity)
    s.mechanics=FixedResults([item]); banner=r.banner('char_all_limited')
    for n in range(7):
        result=s.draw('qq','u',banner,1)
        owned=s.team_of('qq','u')
        assert len(owned)==1 and owned[0].copies==n+1 and owned[0].level==n
        assert owned[0].maxed==(n==6)
        assert result.overflow_bonus==0 and result.remaining==9-n
    result=s.draw('qq','u',banner,1)
    assert result.overflow_bonus==10 and result.remaining==12
    assert s.team_of('qq','u')[0].copies==7 and s.team_of('qq','u')[0].level==6
    result=s.draw('qq','u',banner,1)
    assert result.overflow_bonus==10 and result.remaining==21
    assert store.total_pulls('qq','u')==9 and store.count_history('qq','u')==9

@pytest.mark.parametrize('initial,expected',[(0,30),(6,90),(7,100)])
def test_ten_pull_cap_crossing_and_refund_count(env,initial,expected):
    r,store,s=env; item=r.item('char:KOTONE'); s.mechanics=FixedResults([item])
    for _ in range(initial):store.add_owned('qq','u',item)
    out=s.draw('qq','u',r.banner('char_all_limited'),10)
    assert out.overflow_bonus==expected and out.remaining==expected
    assert s.team_of('qq','u')[0].copies==7
    assert s.quota_of('qq','u').used==10
    assert store.total_pulls('qq','u')==10


def test_only_high_star_characters_and_weapons_persist(env):
    r,store,s=env
    items=[r.item('char:KOTONE'), next(i for i in r.items.values() if i.id.startswith('weapon:') and i.rarity==4),
           next(i for i in r.items.values() if i.id.startswith('persona:')), Item('persona:fake5','高星人格面具','persona',5),
           Item('weapon:low','低星武器','weapon',3)]
    s.mechanics=FixedResults(items)
    s.draw('qq','u',r.banner('char_all_limited'),10)
    assert {e.item.id for e in s.team_of('qq','u')}=={items[0].id,items[1].id}
    assert all(e.copies==2 for e in s.team_of('qq','u'))
    with store._lock:
        raw=store._conn.execute('SELECT * FROM pull_history').fetchall()
    assert len(raw)==4 and all(row['rarity'] in (4,5) and row['item_id'].startswith(('char:','weapon:')) for row in raw)
    assert store.total_pulls('qq','u')==10


def test_collection_and_rewards_work_with_history_disabled(env):
    r,store,s=env; s.record_history=False; item=r.item('char:KOTONE')
    s.mechanics=FixedResults([item]); out=s.draw('qq','u',r.banner('char_all_limited'),10)
    assert out.remaining==30 and s.team_of('qq','u')[0].level==6
    assert store.count_history('qq','u')==0


def test_owner_variants_and_item_rarities_have_separate_levels(env):
    r,store,s=env
    items=[r.item('char:BERRY'),r.item('char:BERRY·Summer'),r.item('weapon:BERRY-weapon5-1'),r.item('weapon:BERRY-weapon4-1')]
    assert all(items)
    for n,item in enumerate(items):
        for _ in range(n+1):store.add_owned('qq','u',item)
    assert {e.item.id:e.level for e in s.team_of('qq','u')}=={i.id:n for n,i in enumerate(items)}
    assert s.team_of('other','u')==() and s.team_of('qq','other')==()


def test_failed_save_rolls_back_owned_and_overflow_reward(env,monkeypatch):
    r,store,s=env; item=r.item('char:KOTONE'); s.mechanics=FixedResults([item])
    for _ in range(6):store.add_owned('qq','u',item)
    before=s.team_of('qq','u'); original=store.save_daily
    def fail(*a,**kw):
        original(*a,**kw)
        raise RuntimeError('quota failure')
    monkeypatch.setattr(store,'save_daily',fail)
    with pytest.raises(RuntimeError):s.draw('qq','u',r.banner('char_all_limited'),10)
    assert s.team_of('qq','u')==before
    assert s.quota_of('qq','u').remaining==10
    assert store.total_pulls('qq','u')==0 and store.count_history('qq','u')==0


def test_new_day_keeps_collection_but_expires_overflow_credit(env):
    r,store,s=env; clock=[1794052799]; s.clock=lambda:clock[0]
    item=r.item('char:KOTONE'); s.mechanics=FixedResults([item])
    s.draw('qq','u',r.banner('char_all_limited'),10)
    assert s.quota_of('qq','u').remaining==30
    clock[0]+=86400
    assert s.quota_of('qq','u').remaining==10
    assert s.team_of('qq','u')[0].level==6
    assert s.draw('qq','u',r.banner('char_all_limited'),1).remaining==19


def test_import_old_histories_is_idempotent_and_never_backpays(tmp_path):
    r=Registry.load(); path=tmp_path/'legacy.db'; store=Store(path)
    char=r.item('char:KOTONE'); weapon=r.item('weapon:KOTONE-weapon5-1')
    store.add_history('qq','u','old',[(char.id,char.name,5,False)]*9+[(weapon.id,weapon.name,5,False)]*2+
                      [('persona:old','人格面具',3,False),('char:unknown','未知角色',5,False)])
    s=GachaService(r,store,record_history=False)
    owned={e.item.id:e.copies for e in s.team_of('qq','u')}
    assert owned=={char.id:7,weapon.id:2}
    assert s.quota_of('qq','u').remaining==10
    store.close(); store=Store(path)
    try:
        s=GachaService(r,store)
        assert {e.item.id:e.copies for e in s.team_of('qq','u')}==owned
        assert s.quota_of('qq','u').remaining==10
        s.mechanics=FixedResults([char])
        assert s.draw('qq','u',r.banner('char_all_limited'),1).overflow_bonus==10
    finally:store.close()


def test_same_item_across_service_connections_has_no_lost_copies_or_rewards(env):
    r,store,s=env; item=r.item('char:KOTONE'); s.mechanics=FixedResults([item])
    other=Store(store.path)
    try:
        second=GachaService(r,other); second.mechanics=FixedResults([item])
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(lambda service:service.draw('qq','u',r.banner('char_all_limited'),1),[s,second]))
        assert s.team_of('qq','u')[0].copies==2
        assert s.quota_of('qq','u').remaining==8
        for _ in range(5):store.add_owned('qq','u',item)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(lambda service:service.draw('qq','u',r.banner('char_all_limited'),1),[s,second]))
        assert sum(out.overflow_bonus for out in outcomes)==20
        assert s.quota_of('qq','u').remaining==26
        assert s.team_of('qq','u')[0].copies==7
    finally:other.close()


def test_team_grouping_preserves_all_items_and_adjacent_special_weapons(env):
    r,_,_=env
    entries=tuple(OwnedItem(i,7 if n%3==0 else 1) for n,i in enumerate(r.items.values()) if collectible(i))
    rows=team_rows(entries); pages=team_pages(entries)
    assert {e.item.id for row in rows for e in row}=={e.item.id for e in entries}
    assert len([e for row in rows for e in row])==len(entries)
    positions={e.item.id:(n,col) for n,row in enumerate(rows) for col,e in enumerate(row)}
    for entry in entries:
        if entry.item.id.startswith('weapon:') and entry.owner in positions:
            assert positions[entry.owner][0]==positions[entry.item.id][0]
            assert positions[entry.owner][1]<positions[entry.item.id][1]
    assert all(len(row)<=4 for row in rows) and all(len(page)<=4 for page in pages)
    assert tuple(row for page in pages for row in page)==rows


def test_team_render_max_effect_and_empty_collection(env):
    r,_,_=env; renderer=Renderer(); item=r.item('char:KOTONE')
    normal=render_team(renderer,team_pages([OwnedItem(item,1)])[0],r,'测试用户',1,1,1,0,10)
    maxed=render_team(renderer,team_pages([OwnedItem(item,7)])[0],r,'测试用户',1,1,1,0,10)
    assert normal.size==maxed.size==(1440,740)
    # Card image changes above the progress labels, proving a visual max-stage effect.
    assert normal.crop((48,247,360,460)).tobytes()!=maxed.crop((48,247,360,460)).tobytes()
    empty=render_team(renderer,(),r,'空收藏',1,1,0,0,10)
    assert empty.size==(1440,740)


def test_selector_acquisition_enters_collection_without_spending_draws(env):
    r,store,s=env; banner=r.banner('char_standard'); item=banner.candidates(5)[0]
    store.save_state('qq','u',banner.pity_group,PityState(pulls=300,totals={banner.id:300}))
    assert s.select_character('qq','u',banner,item.id)==item.name
    assert s.team_of('qq','u')[0].level==0
    assert s.quota_of('qq','u').remaining==10 and store.total_pulls('qq','u')==300


def test_clear_user_removes_collection(env):
    r,store,s=env; store.add_owned('qq','u',r.item('char:KOTONE'))
    store.clear_user('qq','u')
    assert s.team_of('qq','u')==()


def test_overflow_signin_refresh_stack_and_reward_is_not_a_draw(env):
    r,store,s=env; item=r.item('char:KOTONE'); s.mechanics=FixedResults([item])
    result=s.draw('qq','u',r.banner('char_all_limited'),10)
    assert result.remaining==30
    assert s.signin('qq','u')[0].remaining==40
    assert s.refresh_all()==1 and s.quota_of('qq','u').remaining==50
    assert store.total_pulls('qq','u')==10 and s.quota_of('qq','u').used==10


def test_insufficient_quota_does_not_anticipate_duplicate_refunds(env):
    r,store,s=env; s.daily_pulls=0; item=r.item('char:KOTONE')
    for _ in range(7):store.add_owned('qq','u',item)
    s.mechanics=FixedResults([item])
    with pytest.raises(ValueError):s.draw('qq','u',r.banner('char_all_limited'),1)
    assert s.team_of('qq','u')[0].copies==7 and s.quota_of('qq','u').remaining==0
    assert store.total_pulls('qq','u')==0
