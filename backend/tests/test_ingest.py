import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import StockMeta
from app.services.collector.types import StockInfo
from app.services.ingest import upsert_stock_meta


async def _all_stocks(session: AsyncSession) -> list[StockMeta]:
    # populate_existing：upsert 走 core SQL 绕过 ORM identity map，
    # 需强制从 DB 重读，否则拿到缓存的旧对象。
    result = await session.execute(
        select(StockMeta).execution_options(populate_existing=True)
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

    # 改名再 upsert：应更新而非新增（幂等）
    stocks = [StockInfo("600519.SH", "600519", "茅台股份", "SH", "1.600519")]
    await upsert_stock_meta(db_session, stocks)
    rows = await _all_stocks(db_session)
    assert len(rows) == 1
    assert rows[0].name == "茅台股份"


@pytest.mark.asyncio
async def test_upsert_stock_meta_empty(db_session):
    n = await upsert_stock_meta(db_session, [])
    assert n == 0
