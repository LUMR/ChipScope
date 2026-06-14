import pytest
from sqlalchemy import select

from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.services.collector.types import KlineBar, StockInfo
from app.services.ingest import upsert_daily_kline, upsert_stock_meta
from app.utils.time import trading_day_ts


async def _all_stocks(session):
    result = await session.execute(
        select(StockMeta).execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def _all_klines(session):
    result = await session.execute(
        select(DailyKline).execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_upsert_stock_meta_inserts_then_updates(db_session):
    stocks = [StockInfo("600519.SH", "600519", "贵州茅台", "SH", "1.600519")]
    n = await upsert_stock_meta(db_session, stocks)
    assert n == 1
    rows = await _all_stocks(db_session)
    assert len(rows) == 1
    assert rows[0].name == "贵州茅台"
    assert rows[0].secid == "1.600519"

    stocks = [StockInfo("600519.SH", "600519", "茅台股份", "SH", "1.600519")]
    await upsert_stock_meta(db_session, stocks)
    rows = await _all_stocks(db_session)
    assert len(rows) == 1
    assert rows[0].name == "茅台股份"


@pytest.mark.asyncio
async def test_upsert_stock_meta_empty(db_session):
    n = await upsert_stock_meta(db_session, [])
    assert n == 0


@pytest.mark.asyncio
async def test_upsert_daily_kline_normalizes_tz_and_is_idempotent(db_session):
    # DailyKline 有 FK 到 stock_meta，先建元数据
    await upsert_stock_meta(
        db_session,
        [StockInfo("600519.SH", "600519", "贵州茅台", "SH", "1.600519")],
    )
    bars = [
        KlineBar(
            "2026-06-13",
            1680.0,
            1685.0,
            1690.0,
            1675.0,
            10000,
            1.683e9,
            0.3,
            0.8,
            1683.0,
        )
    ]
    n1 = await upsert_daily_kline(db_session, "600519.SH", bars)
    assert n1 == 1
    rows = await _all_klines(db_session)
    assert len(rows) == 1
    # ts 归一化为北京 15:30 的 UTC 时刻
    assert rows[0].ts == trading_day_ts("2026-06-13")
    # NUMERIC 列读回为 Decimal，用 float + approx 比较
    assert float(rows[0].turnover_rate) == pytest.approx(0.8)
    assert float(rows[0].vwap) == pytest.approx(1683.0)

    # 重复 upsert 幂等
    n2 = await upsert_daily_kline(db_session, "600519.SH", bars)
    assert n2 == 1
    rows = await _all_klines(db_session)
    assert len(rows) == 1
