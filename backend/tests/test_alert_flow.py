"""告警链路集成测试（真 PostgreSQL）：日级触发/去重、realtime cooldown、loop 并集。"""
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.alert import AlertEvent, AlertRule
from app.models.base import Base
from app.models.chip import ChipDistribution
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.services.alert_engine import (
    EdgeState,
    evaluate_daily,
    evaluate_realtime,
    load_active_rules,
)
from app.services.collector.tdx_client import RealtimeQuote
from app.utils.time import trading_day_ts

_CST = ZoneInfo("Asia/Shanghai")
_DIST = {"10.0": 0.5, "10.2": 0.5}


def _cst_date(offset_days: int = 0) -> str:
    """北京时间今天 ± offset 天（evaluate_daily 快照新鲜度检查以 CST 日期为准）。"""
    d = datetime.now(timezone.utc).astimezone(_CST).date() + timedelta(days=offset_days)
    return d.isoformat()


def _quote(secucode, price=10.5, last_close=10.0):
    return RealtimeQuote(
        secucode=secucode.split(".")[0], price=price, open=last_close,
        last_close=last_close, high=price, low=last_close,
        vol=1000.0, amount=2e6, bids=[], asks=[],
    )


@pytest_asyncio.fixture
async def flow_db(monkeypatch):
    """独立 engine；seed 元数据、日K、筹码、两条规则 + watchlist。"""
    # 不依赖 .env：强制全局 webhook 为空（事件落为 skipped）
    monkeypatch.setattr(get_settings(), "alert_webhook_url", "")
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, alert_rule, alert_event CASCADE"))
    async with SessionLocal() as s:
        # 父表（stock_meta）先 commit：模型无 relationship，unit-of-work 不按 FK
        # 自动排序父子 INSERT（项目其它测试同此模式）
        s.add_all([
            StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                      market="SH", secid="1.600519"),
            StockMeta(secucode="000001.SZ", code="000001", name="平安银行",
                      market="SZ", secid="0.000001"),
        ])
        await s.commit()
        s.add(DailyKline(secucode="600519.SH", ts=trading_day_ts(_cst_date()),
                         open=9.8, close=10.0, high=10.1, low=9.7, volume=1000,
                         amount=1e6, turnover_rate=0.1, pct_change=2.0, vwap=10.0))
        # 最新今天 + 次新昨天两行筹码快照（新鲜度检查要求最新 = 当天）
        for d, profit in ((_cst_date(), 0.85), (_cst_date(-1), 0.70)):
            s.add(ChipDistribution(
                ts=trading_day_ts(d), secucode="600519.SH", distribution=_DIST,
                decay_coeff=2.0, concentration=0.12, cost_high=11.0, cost_low=9.0,
                profit_ratio=profit, avg_cost=10.0,
            ))
        s.add(AlertRule(
            name="获利盘日级", secucodes=["600519.SH"], enabled=True,
            cooldown_minutes=10,
            conditions=[{"scope": "chip", "metric": "profit_ratio",
                         "op": "gte", "value": 0.8}],
        ))
        s.add(AlertRule(
            name="涨幅实时", secucodes=["000001.SZ"], enabled=True,
            cooldown_minutes=10,
            conditions=[{"scope": "realtime", "metric": "pct_change",
                         "op": "gte", "value": 1.0}],
        ))
        s.add(Watchlist(secucode="600519.SH", scope="default", sort_order=0))
        await s.commit()
    yield SessionLocal
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stock_meta, alert_rule, alert_event CASCADE"))
    await engine.dispose()


async def _events(SessionLocal, **kw):
    async with SessionLocal() as s:
        stmt = select(AlertEvent).order_by(AlertEvent.id)
        for k, v in kw.items():
            stmt = stmt.where(getattr(AlertEvent, k) == v)
        return list((await s.execute(stmt)).scalars().all())


async def _drain_background():
    """等后台发送 task 收尾（无 webhook → skipped 回写）。"""
    from app.services.alert_engine import _background_tasks
    if _background_tasks:
        await asyncio.gather(*list(_background_tasks))


@pytest.mark.asyncio
async def test_evaluate_daily_fires_once_per_trade_date(flow_db):
    SessionLocal = flow_db
    n = await evaluate_daily(SessionLocal)
    assert n == 1
    events = await _events(SessionLocal, secucode="600519.SH")
    assert len(events) == 1
    e = events[0]
    assert e.rule_name == "获利盘日级"
    assert e.stock_name == "贵州茅台"  # 名称快照
    assert e.trade_date is not None
    assert "获利盘" in e.message
    assert e.payload["profit_ratio"] == 0.85
    assert e.payload["prev:profit_ratio"] == 0.70

    await _drain_background()
    events = await _events(SessionLocal, secucode="600519.SH")
    assert events[0].status == "skipped"  # 未配 webhook → skipped

    # 同一 trade_date 二次评估不重复触发
    assert await evaluate_daily(SessionLocal) == 0
    assert len(await _events(SessionLocal, secucode="600519.SH")) == 1


@pytest.mark.asyncio
async def test_evaluate_daily_skips_stale_snapshot(flow_db):
    """旧快照（停牌/当日采集失败）不评估：不触发、不写旧 trade_date 去重键。"""
    SessionLocal = flow_db
    async with SessionLocal() as s:
        s.add(ChipDistribution(
            ts=trading_day_ts("2026-08-19"), secucode="000001.SZ",
            distribution=_DIST, decay_coeff=2.0, concentration=0.12,
            cost_high=11.0, cost_low=9.0, profit_ratio=0.9, avg_cost=10.0,
        ))
        s.add(AlertRule(
            name="旧快照规则", secucodes=["000001.SZ"], enabled=True,
            cooldown_minutes=10,
            conditions=[{"scope": "chip", "metric": "profit_ratio",
                         "op": "gte", "value": 0.8}],
        ))
        await s.commit()
    # 只有 600519（当天快照）触发；000001 旧快照被新鲜度检查跳过
    assert await evaluate_daily(SessionLocal) == 1
    assert await _events(SessionLocal, secucode="000001.SZ") == []
    await _drain_background()


@pytest.mark.asyncio
async def test_evaluate_daily_isolates_per_stock(flow_db):
    """单股坏数据（distribution 键非数字 → float 峰值价抛错）不中断其余股票。"""
    SessionLocal = flow_db
    async with SessionLocal() as s:
        # 000001 排序在 600519 前：坏股先处理，验证 rollback 后继续
        s.add(ChipDistribution(
            ts=trading_day_ts(_cst_date()), secucode="000001.SZ",
            distribution={"abc": 0.5}, decay_coeff=2.0, concentration=0.12,
            cost_high=11.0, cost_low=9.0, profit_ratio=0.9, avg_cost=10.0,
        ))
        s.add(AlertRule(
            name="坏数据股规则", secucodes=["000001.SZ"], enabled=True,
            cooldown_minutes=10,
            conditions=[{"scope": "chip", "metric": "profit_ratio",
                         "op": "gte", "value": 0.8}],
        ))
        await s.commit()
    assert await evaluate_daily(SessionLocal) == 1  # 600519 照常触发
    assert len(await _events(SessionLocal, secucode="600519.SH")) == 1
    await _drain_background()


@pytest.mark.asyncio
async def test_evaluate_realtime_cooldown_dedup(flow_db):
    SessionLocal = flow_db
    rules, names = await load_active_rules(SessionLocal)
    assert names == {"600519.SH": "贵州茅台", "000001.SZ": "平安银行"}
    rt_rules = [r for r in rules if r.name == "涨幅实时"]
    state = EdgeState()

    q = _quote("000001.SZ", price=10.5, last_close=10.0)  # pct +5% ≥ 1
    await evaluate_realtime(SessionLocal, rt_rules, names, "000001.SZ", q, state)
    assert len(await _events(SessionLocal, secucode="000001.SZ")) == 1

    # cooldown 10 分钟内同条件不再触发（事件不新增）
    await evaluate_realtime(SessionLocal, rt_rules, names, "000001.SZ", q, state)
    assert len(await _events(SessionLocal, secucode="000001.SZ")) == 1

    # 不满足条件也不触发
    q_low = _quote("000001.SZ", price=10.05, last_close=10.0)  # pct +0.5%
    await evaluate_realtime(SessionLocal, rt_rules, names, "000001.SZ", q_low, state)
    assert len(await _events(SessionLocal, secucode="000001.SZ")) == 1
    await _drain_background()


@pytest.mark.asyncio
async def test_evaluate_realtime_cross_edge(flow_db):
    """cross_above 需要上一 tick 前值：首 tick 不触发，上穿 tick 触发。"""
    SessionLocal = flow_db
    async with SessionLocal() as s:
        s.add(AlertRule(
            name="现价上穿", secucodes=["000001.SZ"], enabled=True, cooldown_minutes=10,
            conditions=[{"scope": "realtime", "metric": "price",
                         "op": "cross_above", "value": 10.3}],
        ))
        await s.commit()
    rules, names = await load_active_rules(SessionLocal)
    rules = [r for r in rules if r.name == "现价上穿"]
    state = EdgeState()

    # tick1：10.0（低于阈值，记录前值）
    await evaluate_realtime(
        SessionLocal, rules, names, "000001.SZ",
        _quote("000001.SZ", price=10.0, last_close=10.0), state,
    )
    assert await _events(SessionLocal, rule_name="现价上穿") == []
    # tick2：10.5 上穿 10.3 → 触发
    await evaluate_realtime(
        SessionLocal, rules, names, "000001.SZ",
        _quote("000001.SZ", price=10.5, last_close=10.0), state,
    )
    assert len(await _events(SessionLocal, rule_name="现价上穿")) == 1
    await _drain_background()


@pytest.mark.asyncio
async def test_realtime_loop_pulls_watchlist_union_alerts(flow_db, monkeypatch):
    """loop 拉取列表 = watchlist ∪ 活跃告警股票（去重保序）；交易时段内评估触发。"""
    SessionLocal = flow_db
    import app.scheduler as sched

    calls: list[str] = []

    class _FakeTdx:
        async def quotes(self, code):
            calls.append(code)
            return _quote(code, price=10.5, last_close=10.0)

        def close(self):
            pass

    async def _no_cache(q, secucode=None):
        pass

    class _FakeMgr:
        async def broadcast_global(self, data):
            pass

    _orig_read_wl = sched.read_watchlist_secucodes

    async def _read_wl(session_factory=None):
        return await _orig_read_wl(SessionLocal)  # 绑定测试 engine

    monkeypatch.setattr(sched, "TdxClient", _FakeTdx)
    monkeypatch.setattr(sched, "cache_quote", _no_cache)
    monkeypatch.setattr(sched, "manager", _FakeMgr())
    monkeypatch.setattr(sched, "SessionLocal", SessionLocal)
    monkeypatch.setattr(sched, "read_watchlist_secucodes", _read_wl)
    monkeypatch.setattr(sched, "in_trading_window", lambda now: True)  # 强开闸门

    await sched.realtime_loop()
    # watchlist 600519 在前，alert-only 000001 在后，无重复
    assert calls == ["600519", "000001"]
    # 交易时段内 000001 的 realtime 规则被评估并触发
    await _drain_background()
    assert len(await _events(SessionLocal, secucode="000001.SZ")) == 1


@pytest.mark.asyncio
async def test_realtime_loop_skips_evaluation_out_of_window(flow_db, monkeypatch):
    """非交易时段：照常拉行情/缓存，但不评估告警（无事件产生）。"""
    SessionLocal = flow_db
    import app.scheduler as sched

    class _FakeTdx:
        async def quotes(self, code):
            return _quote(code, price=10.5, last_close=10.0)

        def close(self):
            pass

    async def _no_cache(q, secucode=None):
        pass

    class _FakeMgr:
        async def broadcast_global(self, data):
            pass

    _orig_read_wl = sched.read_watchlist_secucodes

    async def _read_wl(session_factory=None):
        return await _orig_read_wl(SessionLocal)

    monkeypatch.setattr(sched, "TdxClient", _FakeTdx)
    monkeypatch.setattr(sched, "cache_quote", _no_cache)
    monkeypatch.setattr(sched, "manager", _FakeMgr())
    monkeypatch.setattr(sched, "SessionLocal", SessionLocal)
    monkeypatch.setattr(sched, "read_watchlist_secucodes", _read_wl)
    monkeypatch.setattr(sched, "in_trading_window", lambda now: False)

    await sched.realtime_loop()
    assert await _events(SessionLocal) == []
