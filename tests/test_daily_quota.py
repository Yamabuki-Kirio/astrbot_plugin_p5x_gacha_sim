"""Daily budget contracts, including midnight, persistence, races and failure atomicity."""
import sys
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.core.registry import Registry
from src.core.store import Store
from src.services.gacha_service import GachaService

@pytest.fixture
def env(tmp_path):
    r=Registry.load(); store=Store(tmp_path/'daily.db')
    clock=[datetime(2026,11,7,15,59,59,tzinfo=timezone.utc).timestamp()]
    service=GachaService(r,store,clock=lambda:clock[0])
    yield r,store,service,clock
    store.close()

def test_base_ten_and_signin_ten_once(env):
    r,store,s,_=env; banner=r.banner('char_all_limited')
    assert s.quota_of('qq','u').remaining==10
    first=s.draw('qq','u',banner,10)
    assert first.remaining==0
    before=s.state_of('qq','u',banner)
    with pytest.raises(ValueError,match='剩余 0 抽'):s.draw('qq','u',banner,10)
    assert s.state_of('qq','u',banner)==before
    quota,claimed=s.signin('qq','u')
    assert claimed and quota.remaining==10 and quota.signed
    quota,claimed=s.signin('qq','u')
    assert not claimed and quota.remaining==10
    second=s.draw('qq','u',banner,10)
    assert second.remaining==0
    with pytest.raises(ValueError):s.draw('qq','u',banner,1)
    assert store.total_pulls('qq','u')==20 and store.count_history('qq','u')==sum(x.rarity in (4,5) and x.item.id.startswith(('char:','weapon:')) for x in first.results+second.results)

def test_early_signin_and_single_ten_share_all_pools(env):
    r,store,s,_=env
    assert s.signin('qq','u')[0].remaining==20
    first=r.resolve('哈姆子'); weapon=r.banner('weapon_all_limited')
    assert s.draw('qq','u',first,1).remaining==19
    assert s.draw('qq','u',weapon,10).remaining==9
    with pytest.raises(ValueError):s.draw('qq','u',r.banner('char_standard'),10)
    assert s.quota_of('qq','u').remaining==9
    for _ in range(9):s.draw('qq','u',r.banner('char_standard'),1)
    assert s.quota_of('qq','u').remaining==0
    assert s.quota_of('qq','other').remaining==10
    assert s.quota_of('other_platform','u').remaining==10

def test_beijing_midnight_reset_does_not_touch_pity_or_lifetime(env):
    r,store,s,clock=env; banner=r.banner('char_all_limited')
    s.signin('qq','u'); s.draw('qq','u',banner,1)
    previous=s.state_of('qq','u',banner)
    assert s.quota_of('qq','u').day=='2026-11-07'
    assert s.quota_of('qq','u').remaining==19
    clock[0]+=1 # UTC16:00 is Beijing00:00; reset without restart or job.
    quota=s.quota_of('qq','u')
    assert quota.day=='2026-11-08' and quota.remaining==10
    assert not quota.signed and quota.used==0 and quota.bonus==0
    assert s.state_of('qq','u',banner)==previous
    assert store.total_pulls('qq','u')==1
    assert s.signin('qq','u')[0].remaining==20
    clock[0]+=86400*3
    assert s.quota_of('qq','u').remaining==10 # no accumulated missed-day rewards

def test_restart_retains_spend_and_signin(env):
    r,store,s,clock=env
    s.signin('qq','u'); s.draw('qq','u',r.banner('char_all_limited'),10)
    other=Store(store.path)
    try:
        restarted=GachaService(r,other,clock=lambda:clock[0])
        assert restarted.quota_of('qq','u').remaining==10
        assert not restarted.signin('qq','u')[1]
        assert restarted.draw('qq','u',r.banner('weapon_all_limited'),10).remaining==0
        assert s.quota_of('qq','u').remaining==0
        clock[0]+=1
        assert restarted.quota_of('qq','u').remaining==10
    finally:other.close()

@pytest.mark.parametrize('history',[True,False])
def test_failed_save_rolls_back_quota_pity_and_history(env,monkeypatch,history):
    r,store,s,_=env; s.record_history=history; banner=r.banner('char_all_limited')
    before=s.state_of('qq','u',banner); s.quota_of('qq','u')
    original=store.save_daily
    def fail(*a,**kw):
        original(*a,**kw)
        raise RuntimeError('write failure')
    monkeypatch.setattr(store,'save_daily',fail)
    with pytest.raises(RuntimeError):s.draw('qq','u',banner,10)
    assert s.quota_of('qq','u').remaining==10
    assert s.state_of('qq','u',banner)==before
    assert store.count_history('qq','u')==0

def test_history_failure_does_not_charge_or_save_pity(env,monkeypatch):
    r,store,s,_=env; banner=r.banner('char_all_limited')
    before=s.state_of('qq','u',banner)
    original=store.add_history
    def fail(*a,**kw):
        original(*a,**kw)
        raise RuntimeError('history failed')
    monkeypatch.setattr(store,'add_history',fail)
    with pytest.raises(RuntimeError):s.draw('qq','u',banner,10)
    assert s.quota_of('qq','u').remaining==10
    assert s.state_of('qq','u',banner)==before
    assert store.count_history('qq','u')==0

def test_two_connections_cannot_double_spend_or_double_claim(env):
    r,store,s,clock=env; other=Store(store.path)
    try:
        services=[s,GachaService(r,other,clock=lambda:clock[0])]
        def attempt(n):
            try:
                services[n%2].draw('qq','u',r.banner('char_all_limited'),10)
                return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            assert sum(pool.map(attempt,range(6)))==1
        def claim(n):return services[n%2].signin('qq','u')[1]
        with ThreadPoolExecutor(max_workers=6) as pool:
            assert sum(pool.map(claim,range(6)))==1
        assert s.quota_of('qq','u').remaining==10
        with ThreadPoolExecutor(max_workers=6) as pool:
            assert sum(pool.map(attempt,range(6)))==1
        assert store.total_pulls('qq','u')==20
        assert s.quota_of('qq','u').remaining==0
    finally:other.close()

def test_configurable_budget_and_invalid_limits(env):
    r,store,_,clock=env
    s=GachaService(r,store,daily_pulls=5,signin_bonus=15,clock=lambda:clock[0])
    assert s.quota_of('qq','u').remaining==5
    assert s.signin('qq','u')[0].remaining==20
    for config in ({'daily_pulls':-1},{'signin_bonus':-1},{'daily_pulls':True},{'daily_pulls':'10'}):
        with pytest.raises(ValueError):GachaService(r,store,**config)
    zero=GachaService(r,store,daily_pulls=0,signin_bonus=0,clock=lambda:clock[0])
    assert zero.quota_of('qq','zero').remaining==0
    assert zero.signin('qq','zero')[0].remaining==0
    with pytest.raises(ValueError):zero.draw('qq','zero',r.banner('char_all_limited'),1)

def test_invalid_draw_does_not_consume(env):
    r,store,s,_=env
    with pytest.raises(ValueError):s.draw('qq','u',r.banner('char_all_limited'),11)
    assert s.quota_of('qq','u').remaining==10


def test_upgrade_existing_database_preserves_old_state(tmp_path):
    import sqlite3,json
    from src.core.models import PityState
    path=tmp_path/'legacy.db'; connection=sqlite3.connect(path)
    connection.executescript("""CREATE TABLE pity_state(
        platform_id TEXT,user_id TEXT,group_id TEXT,state_json TEXT,updated_at REAL,
        PRIMARY KEY(platform_id,user_id,group_id));""")
    before=PityState(pity5=17,guaranteed5=True,pulls=137)
    connection.execute('INSERT INTO pity_state VALUES(?,?,?,?,?)',('qq','u','char',json.dumps(before.to_dict()),0))
    connection.commit(); connection.close()
    store=Store(path)
    try:
        s=GachaService(Registry.load(),store)
        assert store.load_state('qq','u','char')==before
        assert s.quota_of('qq','u').remaining==10
        assert s.signin('qq','u')[0].remaining==20
        assert store.load_state('qq','u','char')==before
    finally:store.close()


def test_failed_signin_does_not_mark_claimed(env,monkeypatch):
    _,store,s,_=env; original=store.save_daily
    def fail(*a,**kw):
        original(*a,**kw)
        raise RuntimeError('signin failure')
    monkeypatch.setattr(store,'save_daily',fail)
    with pytest.raises(RuntimeError):s.signin('qq','u')
    quota=s.quota_of('qq','u')
    assert quota.remaining==10 and not quota.signed and quota.bonus==0
    monkeypatch.setattr(store,'save_daily',original)
    assert s.signin('qq','u')[1]


def test_refresh_matches_zero_ten_twenty_examples_and_preserves_state(env):
    r,store,s,_=env; banner=r.banner('char_all_limited')
    first=s.draw('qq','zero',banner,10)
    s.quota_of('qq','ten')
    s.signin('qq','twenty')
    saved=s.state_of('qq','zero',banner)
    assert s.refresh_all()==3
    assert s.quota_of('qq','zero').remaining==10
    assert s.quota_of('qq','ten').remaining==20
    assert s.quota_of('qq','twenty').remaining==30
    assert not s.quota_of('qq','zero').signed
    assert s.quota_of('qq','twenty').signed
    assert s.state_of('qq','zero',banner)==saved
    assert store.total_pulls('qq','zero')==10 and store.count_history('qq','zero')==sum(x.rarity in (4,5) and x.item.id.startswith(('char:','weapon:')) for x in first.results)
    assert s.signin('qq','ten')[0].remaining==30
    assert not s.signin('qq','twenty')[1]
    assert s.refresh_all()==3
    assert s.quota_of('qq','zero').remaining==20
    assert s.quota_of('qq','ten').remaining==40
    assert s.quota_of('qq','twenty').remaining==40


def test_refresh_registers_legacy_accounts_and_resets_old_day(env):
    r,store,s,clock=env; banner=r.banner('char_all_limited')
    s.signin('qq','old'); s.draw('qq','old',banner,10)
    from src.core.models import PityState
    store.save_state('other_platform','legacy',banner.pity_group,PityState(pulls=50,pity5=7))
    store.set_default_banner('qq','pref_only',banner.id)
    clock[0]+=1
    assert s.refresh_all()==3
    for platform,user in [('qq','old'),('other_platform','legacy'),('qq','pref_only')]:
        quota=s.quota_of(platform,user)
        assert quota.remaining==20 and not quota.signed and quota.used==0
    assert s.quota_of('qq','new_after_refresh').remaining==10
    assert store.load_state('other_platform','legacy',banner.pity_group).pulls==50
    clock[0]+=86400
    assert s.quota_of('qq','old').remaining==10


def test_refresh_rolls_back_if_failed(env,monkeypatch):
    _,store,s,_=env; s.quota_of('qq','u')
    original=store.refresh_daily_all
    def fail(*a,**kw):
        original(*a,**kw)
        raise RuntimeError('refresh failure')
    monkeypatch.setattr(store,'refresh_daily_all',fail)
    with pytest.raises(RuntimeError):s.refresh_all()
    assert s.quota_of('qq','u').remaining==10


def test_refresh_and_signin_race_retains_both_rewards(env):
    r,store,s,clock=env; s.quota_of('qq','u'); other=Store(store.path)
    try:
        second=GachaService(r,other,clock=lambda:clock[0])
        with ThreadPoolExecutor(max_workers=2) as pool:
            refresh=pool.submit(s.refresh_all)
            signin=pool.submit(second.signin,'qq','u')
            assert refresh.result()==1 and signin.result()[1]
        quota=s.quota_of('qq','u')
        assert quota.remaining==30 and quota.signed
    finally:other.close()


def test_refresh_zero_remains_plus_ten_after_limit_reduced(env):
    r,_,s,_=env
    s.draw('qq','u',r.banner('char_all_limited'),10)
    s.daily_pulls=5
    assert s.quota_of('qq','u').remaining==0
    assert s.refresh_all()==1
    assert s.quota_of('qq','u').remaining==10


@pytest.mark.parametrize('count',[20,30,40])
def test_multi_draw_atomic_success_and_rollback(env,monkeypatch,count):
    r,store,s,_=env
    s.daily_pulls=100
    banner=r.banner('char_all_limited')
    outcome=s.draw('qq','u',banner,count)
    assert len(outcome.results)==count and outcome.cost==banner.cost*count
    assert store.total_pulls('qq','u')==count
    assert s.quota_of('qq','u').used==count
    before=s.state_of('qq','u',banner)
    owned=store.owned_items('qq','u')
    remaining=s.quota_of('qq','u').remaining
    original=store.add_owned
    calls=[0]
    def fail(*args):
        calls[0]+=1
        result=original(*args)
        if calls[0]==15:raise RuntimeError('midway failure')
        return result
    monkeypatch.setattr(store,'add_owned',fail)
    with pytest.raises(RuntimeError):s.draw('qq','u',banner,count)
    assert s.state_of('qq','u',banner)==before
    assert s.quota_of('qq','u').remaining==remaining
    assert store.owned_items('qq','u')==owned


def test_multi_draw_cannot_spend_future_duplicate_rewards(env,monkeypatch):
    r,store,s,_=env
    s.daily_pulls=10
    with pytest.raises(ValueError,match='本次需要 20 抽'):
        s.draw('qq','u',r.banner('char_all_limited'),20)
    for invalid in (True,20.0,0,11,50):
        with pytest.raises(ValueError):s.draw('qq','u',r.banner('char_all_limited'),invalid)
