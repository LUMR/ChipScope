import pandas as pd
import pytest
from datetime import date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.config import get_settings
from app.models.base import Base
from app.models.kline import DailyKline
from app.services.kline_archive import (
    archive_daily_klines, reset_daily_kline_archive_state,
)


class _FakeTdx:
    async def stocks(self, market: int):
        if market == 1:
            return pd.DataFrame({"code": ["600519"], "name": ["贵州茅台"],
                                 "volunit": [100], "decimal_point": [2], "pre_close": [100.0]})
        return pd.DataFrame({"code": ["000001"], "name": ["平安银行"],
                             "volunit": [100], "decimal_point": [2], "pre_close": [10.0]})

    async def daily_bars(self, symbol: str, count: int = 250, float_shares: float = 0.0):
        from app.services.collector.types import KlineBar
        # 返回两根，第二根日期为 trade_date
        return [KlineBar("2026-06-23", 99, 100, 101, 98, 1000, 1e7, 1.0, 0.1, 100),
                KlineBar("2026-06-24", 100, 105, 106, 99, 2000, 2e7, 5.0, 0.2, 105)]


@pytest.mark.asyncio
async def test_archive_daily_klines_upserts(db_session):
    _engine = create_async_engine(get_settings().database_url)
    _factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, daily_kline CASCADE"))

    reset_daily_kline_archive_state()
    result = await archive_daily_klines(_factory, _FakeTdx(), date(2026, 6, 24), count=10)
    assert result == {"trade_date": "2026-06-24", "total": 2, "ok": 2, "failed": 0}

    # daily_bars 返回两根（多日回档），secucode 用 DISTINCT 去重到“只看哪些股票落库”。
    rows = (await db_session.execute(
        select(DailyKline.secucode).distinct().order_by(DailyKline.secucode)
    )).scalars().all()
    assert rows == ["000001.SZ", "600519.SH"]
    await _engine.dispose()
