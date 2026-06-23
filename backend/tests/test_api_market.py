from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import app
from app.models.minute_quote import MinuteQuote
from app.models.stock import StockMeta
from app.services import market_minute as mm


@pytest.fixture(autouse=True)
def _clean_cache():
    mm.reset_caches()
    yield
    mm.reset_caches()


@pytest.mark.asyncio
async def test_overview_no_data_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/market/minute/overview", params={"date": "2020-01-01"})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_overview_ranking_stock_dates(db_session):
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()
    db_session.add(MinuteQuote(trade_date=date(2026, 6, 18), secucode="600519.SH",
                               data=[{"t": "09:31", "price": 110.0, "vol": 5}], pre_close=100))
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        dates = (await ac.get("/api/market/minute/dates")).json()
        assert dates == ["2026-06-18"]

        ov = (await ac.get("/api/market/minute/overview", params={"date": "2026-06-18"})).json()
        assert ov["trade_date"] == "2026-06-18"
        assert ov["summary"]["with_pre_close"] == 1

        rk = (await ac.get("/api/market/minute/ranking",
                           params={"date": "2026-06-18", "time": "09:31"})).json()
        assert rk["gainers"][0]["secucode"] == "600519.SH"

        st = (await ac.get("/api/market/minute/stock",
                           params={"date": "2026-06-18", "secucode": "600519.SH"})).json()
        assert st["pre_close"] == 100.0 and st["points"][0]["pct"] == 10.0


@pytest.mark.asyncio
async def test_ranking_invalid_time_422(db_session):
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()
    db_session.add(MinuteQuote(trade_date=date(2026, 6, 18), secucode="600519.SH",
                               data=[{"t": "09:31", "price": 110.0, "vol": 5}], pre_close=100))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/market/minute/ranking",
                         params={"date": "2026-06-18", "time": "08:00"})
        assert r.status_code == 422
