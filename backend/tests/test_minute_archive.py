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
            "pre_close": [0.0] * 6,
        }
    )
    sh = _filter_a_shares(df, market=1)
    assert {s.code for s in sh} == {"600519"}
    sz = _filter_a_shares(df, market=0)
    assert {s.code for s in sz} == {"000001", "300750"}


def test_filter_a_shares_empty():
    assert _filter_a_shares(None, market=1) == []
    assert _filter_a_shares(pd.DataFrame(), market=0) == []


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
         "volunit": [100, 100], "decimal_point": [2, 2], "pre_close": [0.0, 0.0]}
    )
    sz_df = pd.DataFrame(
        {"code": ["000001", "159915"], "name": ["平安银行", "ETF"],
         "volunit": [100, 100], "decimal_point": [2, 2], "pre_close": [0.0, 0.0]}
    )
    codes = await refresh_stock_universe(SessionLocal, _FakeTdx(sh_df, sz_df))
    assert set(codes) == {"600519.SH", "000001.SZ"}
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
    n1 = await upsert_minute_quote(db_session, date(2026, 6, 22), "600519.SH", pts)
    assert n1 == 1

    pts2 = [{"t": "09:31", "price": 11.0, "vol": 200}]
    n2 = await upsert_minute_quote(db_session, date(2026, 6, 22), "600519.SH", pts2)
    assert n2 == 1  # 覆盖，不新增

    rows = (await db_session.execute(
        select(MinuteQuote).where(MinuteQuote.secucode == "600519.SH")
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].data == pts2  # 已被覆盖


class _FakeArchiveTdx:
    """fake TdxClient：stocks 给清单；minute_time 给分时点（第 3 只抛错测 failed）。"""

    def __init__(self):
        self.minute_calls = []

    async def stocks(self, market: int):
        if market == 1:
            return pd.DataFrame({"code": ["600519"], "name": ["贵州茅台"],
                                 "volunit": [100], "decimal_point": [2], "pre_close": [0.0]})
        return pd.DataFrame({"code": ["000001", "300750"], "name": ["平安银行", "宁德时代"],
                             "volunit": [100, 100], "decimal_point": [2, 2],
                             "pre_close": [0.0, 0.0]})

    async def minute_time(self, symbol: str, date=None):
        self.minute_calls.append((symbol, date))
        if symbol == "300750":
            raise RuntimeError("boom")
        return [{"t": "09:31", "price": 10.0, "vol": 100}]


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

    await _engine.dispose()
