import httpx
import pytest

from app.services.collector.eastmoney import EastMoneyClient


@pytest.mark.asyncio
async def test_list_stocks_parses_market_and_secid(respx_mock):
    respx_mock.get("https://push2.eastmoney.com/api/qt/clist/get").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "list": [
                        {"f12": "600519", "f13": 1, "f14": "贵州茅台"},
                        {"f12": "000001", "f13": 0, "f14": "平安银行"},
                    ]
                }
            },
        )
    )
    async with EastMoneyClient() as em:
        stocks = await em.list_stocks()
    assert stocks[0].secucode == "600519.SH"
    assert stocks[0].secid == "1.600519"
    assert stocks[0].market == "SH"
    assert stocks[1].secucode == "000001.SZ"
    assert stocks[1].secid == "0.000001"


@pytest.mark.asyncio
async def test_list_stocks_empty_when_no_data(respx_mock):
    respx_mock.get("https://push2.eastmoney.com/api/qt/clist/get").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with EastMoneyClient() as em:
        stocks = await em.list_stocks()
    assert stocks == []
