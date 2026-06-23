from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.main import app
from app.models.base import Base
from app.models.minute_quote import MinuteQuote
from app.models.stock import StockMeta
from app.services import market_minute as mm


@pytest.fixture(autouse=True)
def _clean_cache():
    mm.reset_caches()
    yield
    mm.reset_caches()


@pytest_asyncio.fixture
async def market_client():
    """独立 engine + dependency_overrides，对齐 test_api_watchlist::watchlist_client 模式。"""
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, minute_quote CASCADE"))

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    from app.api.deps import get_db
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, SessionLocal

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_overview_no_data_404(market_client):
    client, _ = market_client
    r = await client.get("/api/market/minute/overview", params={"date": "2020-01-01"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_overview_ranking_stock_dates(market_client):
    client, SessionLocal = market_client

    async with SessionLocal() as s:
        s.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                         market="SH", secid="1.600519"))
        await s.flush()  # 确保 stock_meta 先 INSERT，满足 FK
        s.add(MinuteQuote(trade_date=date(2026, 6, 18), secucode="600519.SH",
                          data=[{"t": "09:31", "price": 110.0, "vol": 5}], pre_close=100))
        await s.commit()

    dates = (await client.get("/api/market/minute/dates")).json()
    assert dates == ["2026-06-18"]

    ov = (await client.get("/api/market/minute/overview", params={"date": "2026-06-18"})).json()
    assert ov["trade_date"] == "2026-06-18"
    assert ov["summary"]["with_pre_close"] == 1

    rk = (await client.get("/api/market/minute/ranking",
                           params={"date": "2026-06-18", "time": "09:31"})).json()
    assert rk["gainers"][0]["secucode"] == "600519.SH"

    st = (await client.get("/api/market/minute/stock",
                           params={"date": "2026-06-18", "secucode": "600519.SH"})).json()
    assert st["pre_close"] == 100.0 and st["points"][0]["pct"] == 10.0


@pytest.mark.asyncio
async def test_ranking_invalid_time_422(market_client):
    client, SessionLocal = market_client

    async with SessionLocal() as s:
        s.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                         market="SH", secid="1.600519"))
        await s.flush()  # 确保 stock_meta 先 INSERT，满足 FK
        s.add(MinuteQuote(trade_date=date(2026, 6, 18), secucode="600519.SH",
                          data=[{"t": "09:31", "price": 110.0, "vol": 5}], pre_close=100))
        await s.commit()

    r = await client.get("/api/market/minute/ranking",
                         params={"date": "2026-06-18", "time": "08:00"})
    assert r.status_code == 422
