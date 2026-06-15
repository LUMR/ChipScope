import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist


@pytest_asyncio.fixture
async def db_with_watchlist():
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stock_meta, watchlist CASCADE"))
    async with SessionLocal() as s:
        s.add_all([
            StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                      market="SH", secid="1.600519"),
            StockMeta(secucode="000001.SZ", code="000001", name="平安银行",
                      market="SZ", secid="0.000001"),
        ])
        await s.commit()
    yield SessionLocal
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stock_meta, watchlist CASCADE"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_read_watchlist_codes(db_with_watchlist):
    SessionLocal = db_with_watchlist
    async with SessionLocal() as s:
        s.add_all([
            Watchlist(secucode="600519.SH", scope="default", sort_order=1),
            Watchlist(secucode="000001.SZ", scope="default", sort_order=0),
        ])
        await s.commit()

    from app.scheduler import read_watchlist_secucodes
    codes = await read_watchlist_secucodes(SessionLocal)
    assert codes == ["000001.SZ", "600519.SH"]  # 按 sort_order


@pytest.mark.asyncio
async def test_seed_when_empty(db_with_watchlist):
    SessionLocal = db_with_watchlist
    from app.scheduler import seed_watchlist_if_empty
    n = await seed_watchlist_if_empty(SessionLocal)
    assert n >= 1  # 至少种入存在于 stock_meta 的
    from app.scheduler import read_watchlist_secucodes
    codes = await read_watchlist_secucodes(SessionLocal)
    assert "600519.SH" in codes
    # 再 seed 不重复
    n2 = await seed_watchlist_if_empty(SessionLocal)
    assert n2 == 0
