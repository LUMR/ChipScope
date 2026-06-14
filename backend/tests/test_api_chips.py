import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.chip import ChipDistribution
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.utils.time import trading_day_ts


@pytest_asyncio.fixture
async def api_client():
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE stock_meta, daily_kline, chip_distribution CASCADE"
        ))
    async with SessionLocal() as s:
        s.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                        market="SH", secid="1.600519"))
        await s.commit()
        s.add(DailyKline(
            ts=trading_day_ts("2026-06-13"), secucode="600519.SH",
            open=11.0, close=11.5, high=12.0, low=11.0,
            volume=10000, amount=1.15e8, turnover_rate=5.0,
            pct_change=0.5, vwap=11.3,
        ))
        await s.commit()
        s.add(ChipDistribution(
            ts=trading_day_ts("2026-06-13"), secucode="600519.SH",
            distribution={"11.00": 0.5, "12.00": 0.5}, decay_coeff=2.0,
            concentration=0.09, cost_high=12.0, cost_low=11.0,
            profit_ratio=0.5, avg_cost=11.5,
        ))
        await s.commit()

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    from app.api.deps import get_db
    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE stock_meta, daily_kline, chip_distribution CASCADE"
        ))
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_chips_latest(api_client):
    r = await api_client.get("/api/stocks/600519.SH/chips")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert float(data[0]["profit_ratio"]) == 0.5
    assert data[0]["distribution"]["11.00"] == 0.5


@pytest.mark.asyncio
async def test_get_chips_history(api_client):
    r = await api_client.get("/api/stocks/600519.SH/chips/history")
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_get_pattern(api_client):
    r = await api_client.get("/api/stocks/600519.SH/pattern")
    assert r.status_code == 200
    data = r.json()
    assert "latest" in data and "trend" in data
    assert data["current_price"] == 11.5


@pytest.mark.asyncio
async def test_get_chips_empty(api_client):
    r = await api_client.get("/api/stocks/999999.SH/chips")
    assert r.status_code == 200
    assert r.json() == []
