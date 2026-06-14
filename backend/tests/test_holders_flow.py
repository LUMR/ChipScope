import httpx
import pytest
from sqlalchemy import select

from app.models.holder import HolderSummary
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.types import StockInfo
from app.services.ingest import upsert_holders, upsert_stock_meta


@pytest.mark.asyncio
async def test_fetch_holders_parses(respx_mock):
    respx_mock.get("https://datacenter-web.eastmoney.com/api/data/v1/get").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "data": [
                        {
                            "HOLDER_NAME": "香港中央结算",
                            "HOLD_NUM": 1000000,
                            "HOLD_RATIO": 5.5,
                            "HOLDER_NEW": -10000,
                            "SECUCODE": "600519.SH",
                            "NOTICE_DATE": "2026-03-31",
                        }
                    ]
                }
            },
        )
    )
    async with EastMoneyClient() as em:
        rows = await em.fetch_holders("600519.SH")
    assert len(rows) == 1
    assert rows[0]["HOLDER_NAME"] == "香港中央结算"


@pytest.mark.asyncio
async def test_fetch_holders_empty(respx_mock):
    respx_mock.get("https://datacenter-web.eastmoney.com/api/data/v1/get").mock(
        return_value=httpx.Response(200, json={"result": None})
    )
    async with EastMoneyClient() as em:
        assert await em.fetch_holders("600519.SH") == []


@pytest.mark.asyncio
async def test_upsert_holders_computes_decay(db_session):
    rows = [
        {"NOTICE_DATE": "2026-03-31", "HOLDER_NAME": "A", "HOLD_NUM": 1000,
         "HOLD_RATIO": 50.0, "HOLDER_NEW": 0},
    ]
    n = await upsert_holders(db_session, "600519.SH", rows)
    assert n == 1
    s = (
        await db_session.execute(
            select(HolderSummary).execution_options(populate_existing=True)
        )
    ).scalars().first()
    assert float(s.top10_ratio) == 50.0
    # 衰减系数 A = 1/(1 - 0.5) = 2.0
    assert float(s.decay_coeff) == 2.0
