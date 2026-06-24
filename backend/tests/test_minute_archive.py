import pandas as pd
import pytest

from sqlalchemy import select

from app.models.stock import StockMeta
from app.services.minute_archive import _filter_a_shares, refresh_stock_universe
from app.services.collector.types import StockInfo


def test_filter_a_shares_keeps_a_drops_index_bond():
    df = pd.DataFrame(
        {
            "code": ["600519", "999999", "113001", "000001", "300750", "159915"],
            "name": ["贵州茅台", "上证指数", "可转债", "平安银行", "宁德时代", "ETF"],
            "volunit": [100] * 6,
            "decimal_point": [2] * 6,
            "pre_close": [1685.0, 4090.0, 0.0, 12.3, 210.5, 1.5],
        }
    )
    sh = _filter_a_shares(df, market=1)
    assert {s.code for s in sh} == {"600519"}
    assert sh[0].pre_close == 1685.0
    sz = _filter_a_shares(df, market=0)
    assert {s.code for s in sz} == {"000001", "300750"}
    assert {s.code: s.pre_close for s in sz} == {"000001": 12.3, "300750": 210.5}


def test_filter_a_shares_empty():
    assert _filter_a_shares(None, market=1) == []
    assert _filter_a_shares(pd.DataFrame(), market=0) == []


def test_filter_a_shares_strips_null_bytes_in_name():
    """mootdx stocks() 的 name 含尾部 NULL 字节填充，须清理否则 PG UTF8 列拒收。"""
    df = pd.DataFrame(
        {
            "code": ["600519", "000001"],
            "name": ["贵州茅台\x00\x00", "平安银行\x00"],
            "volunit": [100, 100],
            "decimal_point": [2, 2],
            "pre_close": [0.0, 0.0],
        }
    )
    sh = _filter_a_shares(df, market=1)
    assert sh[0].name == "贵州茅台"
    sz = _filter_a_shares(df, market=0)
    assert sz[0].name == "平安银行"


class _FakeTdx:
    """fake TdxClient：stocks 返回预设 DataFrame。"""

    def __init__(self, sh_df, sz_df):
        self._sh = sh_df
        self._sz = sz_df
        self.calls = []

    async def stocks(self, market: int):
        self.calls.append(market)
        return self._sh if market == 1 else self._sz


@pytest.mark.asyncio
async def test_refresh_stock_universe_upserts_a_shares(db_session):
    from app.database import SessionLocal

    sh_df = pd.DataFrame(
        {"code": ["600519", "999999"], "name": ["贵州茅台", "上证指数"],
         "volunit": [100, 100], "decimal_point": [2, 2], "pre_close": [1685.0, 4090.0]}
    )
    sz_df = pd.DataFrame(
        {"code": ["000001", "159915"], "name": ["平安银行", "ETF"],
         "volunit": [100, 100], "decimal_point": [2, 2], "pre_close": [12.3, 1.5]}
    )
    stocks = await refresh_stock_universe(SessionLocal, _FakeTdx(sh_df, sz_df))
    assert {s.secucode for s in stocks} == {"600519.SH", "000001.SZ"}
    assert {s.secucode: s.pre_close for s in stocks} == {"600519.SH": 1685.0, "000001.SZ": 12.3}
    rows = (await db_session.execute(
        select(StockMeta.code).order_by(StockMeta.code)
    )).scalars().all()
    assert rows == ["000001", "600519"]


@pytest.mark.asyncio
async def test_upsert_minute_quote_insert_and_idempotent(db_session):
    from datetime import date
    from app.models.minute_quote import MinuteQuote
    from app.services.minute_archive import upsert_minute_quote

    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()

    pts = [{"t": "09:31", "price": 10.0, "vol": 100}]
    n1 = await upsert_minute_quote(db_session, date(2026, 6, 22), "600519.SH", pts, pre_close=1685.0)
    assert n1 == 1

    pts2 = [{"t": "09:31", "price": 11.0, "vol": 200}]
    n2 = await upsert_minute_quote(db_session, date(2026, 6, 22), "600519.SH", pts2, pre_close=1685.0)
    assert n2 == 1

    row = (await db_session.execute(
        select(MinuteQuote).where(MinuteQuote.secucode == "600519.SH")
    )).scalar_one()
    assert row.data == pts2
    assert float(row.pre_close) == 1685.0


class _FakeArchiveTdx:
    """fake TdxClient：stocks 给清单；minute_time 给分时点（第 3 只抛错测 failed）。"""

    def __init__(self):
        self.minute_calls = []

    async def stocks(self, market: int):
        if market == 1:
            return pd.DataFrame({"code": ["600519"], "name": ["贵州茅台"],
                                 "volunit": [100], "decimal_point": [2], "pre_close": [1685.0]})
        return pd.DataFrame({"code": ["000001", "300750"], "name": ["平安银行", "宁德时代"],
                             "volunit": [100, 100], "decimal_point": [2, 2],
                             "pre_close": [12.3, 210.5]})

    async def minute_time(self, symbol: str, date=None):
        self.minute_calls.append((symbol, date))
        if symbol == "300750":
            raise RuntimeError("boom")
        return [{"t": "09:31", "price": 10.0, "vol": 100}]

    async def daily_bars(self, symbol: str, count: int = 200, float_shares: float = 0.0):
        from app.services.collector.types import KlineBar
        pc = {"600519": 1700.0, "000001": 12.5}.get(symbol, 100.0)
        # 目标日 2026-06-22 的前一交易日 = 2026-06-19
        return [KlineBar("2026-06-18", pc, pc, pc, pc, 1000, 1e8, 0.0, 0.0, pc),
                KlineBar("2026-06-19", pc, pc, pc, pc, 1000, 1e8, 0.0, 0.0, pc)]


@pytest.mark.asyncio
async def test_archive_minute_quotes_main_flow(db_session):
    from datetime import date
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.config import get_settings
    from app.models.base import Base
    from sqlalchemy import text
    from app.services.minute_archive import (
        archive_minute_quotes, get_archive_status, reset_archive_state,
    )

    # 用独立 engine + session_factory，避免复用模块级 SessionLocal 导致
    # Windows ProactorEventLoop 跨 loop 连接泄漏。
    _engine = create_async_engine(get_settings().database_url)
    _factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "TRUNCATE stock_meta, minute_quote CASCADE"
        ))

    reset_archive_state()
    progress = []

    def on_progress(done, total, failed):
        progress.append((done, total, failed))

    result = await archive_minute_quotes(
        _factory, _FakeArchiveTdx(), date(2026, 6, 22), on_progress=on_progress
    )
    assert result == {"trade_date": "2026-06-22", "total": 3, "ok": 2, "failed": 1}
    assert get_archive_status() is None  # archive_minute_quotes 不自设状态，由调用方管理
    assert progress[-1] == (3, 3, 1)  # 末次进度为完成态

    # 断言：db_session 和 _factory 共享同一测试库
    from app.models.minute_quote import MinuteQuote
    rows = (await db_session.execute(
        select(MinuteQuote.secucode).order_by(MinuteQuote.secucode)
    )).scalars().all()
    assert rows == ["000001.SZ", "600519.SH"]

    # pre_close 随分时落库
    pq_rows = (await db_session.execute(
        select(MinuteQuote.secucode, MinuteQuote.pre_close).order_by(MinuteQuote.secucode)
    )).all()
    # 历史日 pre_close 由日K推算（目标日 2026-06-22 前一交易日 2026-06-19 收盘），
    # 而非 stocks() 的 today 昨收
    assert {r[0]: float(r[1]) for r in pq_rows} == {"000001.SZ": 12.5, "600519.SH": 1700.0}

    await _engine.dispose()


def test_prev_close_from_bars_picks_latest_before_target():
    from app.services.minute_archive import prev_close_from_bars
    from app.services.collector.types import KlineBar
    bars = [
        KlineBar("2026-06-18", 0, 1685, 0, 0, 0, 0, 0, 0, 0),
        KlineBar("2026-06-19", 0, 1700, 0, 0, 0, 0, 0, 0, 0),
        KlineBar("2026-06-22", 0, 1710, 0, 0, 0, 0, 0, 0, 0),  # 目标日本身，排除
    ]
    assert prev_close_from_bars(bars, "2026-06-22") == 1700.0


def test_prev_close_from_bars_unordered_takes_max_date():
    from app.services.minute_archive import prev_close_from_bars
    from app.services.collector.types import KlineBar
    bars = [
        KlineBar("2026-06-22", 0, 1710, 0, 0, 0, 0, 0, 0, 0),
        KlineBar("2026-06-18", 0, 1685, 0, 0, 0, 0, 0, 0, 0),
        KlineBar("2026-06-19", 0, 1700, 0, 0, 0, 0, 0, 0, 0),
    ]
    assert prev_close_from_bars(bars, "2026-06-22") == 1700.0


def test_prev_close_from_bars_none_when_no_candidate():
    from app.services.minute_archive import prev_close_from_bars
    from app.services.collector.types import KlineBar
    assert prev_close_from_bars([], "2026-06-22") is None
    bars = [KlineBar("2026-06-25", 0, 1710, 0, 0, 0, 0, 0, 0, 0)]  # 均 >= 目标日
    assert prev_close_from_bars(bars, "2026-06-22") is None
