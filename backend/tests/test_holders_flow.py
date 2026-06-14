import httpx
import pytest

from app.services.collector.eastmoney import EastMoneyClient


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
