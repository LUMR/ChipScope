from datetime import date

import pytest

from sqlalchemy import select

from app.models.minute_quote import MinuteQuote
from app.models.stock import StockMeta


@pytest.mark.asyncio
async def test_minute_quote_insert_and_select(db_session):
    # 外键依赖：先建 stock_meta
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()

    db_session.add(MinuteQuote(
        trade_date=date(2026, 6, 22),
        secucode="600519.SH",
        data=[{"t": "09:31", "price": 1210.31, "vol": 1692}],
    ))
    await db_session.commit()

    row = (
        await db_session.execute(
            select(MinuteQuote).where(
                MinuteQuote.secucode == "600519.SH",
                MinuteQuote.trade_date == date(2026, 6, 22),
            )
        )
    ).scalar_one()
    assert row.data == [{"t": "09:31", "price": 1210.31, "vol": 1692}]
