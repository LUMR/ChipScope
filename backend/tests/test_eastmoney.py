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


@pytest.mark.asyncio
async def test_fetch_daily_kline_parses_and_computes_vwap(respx_mock):
    # 一行: 日期,开,收,高,低,量(手),额,振幅,涨跌幅,涨跌额,换手率
    sample = "2026-06-13,1680.00,1685.00,1690.00,1675.00,10000,1683000000,0.89,0.30,5.0,0.8"
    respx_mock.get("https://push2his.eastmoney.com/api/qt/stock/kline/get").mock(
        return_value=httpx.Response(200, json={"data": {"klines": [sample]}})
    )
    async with EastMoneyClient() as em:
        bars = await em.fetch_daily_kline("1.600519", "20260101", "20261231")
    assert len(bars) == 1
    b = bars[0]
    assert b.date == "2026-06-13"
    assert b.close == 1685.00
    assert b.volume == 10000
    assert b.turnover_rate == 0.8
    assert b.pct_change == 0.30
    # vwap = amount / (vol*100) = 1683000000 / (10000*100) = 1683.0
    assert b.vwap == 1683.0


@pytest.mark.asyncio
async def test_fetch_daily_kline_zero_volume_no_div_zero(respx_mock):
    sample = "2026-06-13,0,0,0,0,0,0,0,0,0,0"  # 停牌
    respx_mock.get("https://push2his.eastmoney.com/api/qt/stock/kline/get").mock(
        return_value=httpx.Response(200, json={"data": {"klines": [sample]}})
    )
    async with EastMoneyClient() as em:
        bars = await em.fetch_daily_kline("1.600519", "20260101", "20261231")
    assert bars[0].vwap == 0.0


@pytest.mark.asyncio
async def test_fetch_daily_kline_handles_missing_data(respx_mock):
    respx_mock.get("https://push2his.eastmoney.com/api/qt/stock/kline/get").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with EastMoneyClient() as em:
        bars = await em.fetch_daily_kline("1.600519", "20260101", "20261231")
    assert bars == []


@pytest.mark.asyncio
async def test_search_stocks_parses_sh_and_sz(respx_mock):
    respx_mock.get("https://searchapi.eastmoney.com/api/suggest/get").mock(
        return_value=httpx.Response(
            200,
            json={"QuotationCodeTable": {"Data": [
                {"Code": "600519", "Name": "贵州茅台", "MktNum": "1"},
                {"Code": "000001", "Name": "平安银行", "MktNum": "0"},
            ]}},
        )
    )
    async with EastMoneyClient() as em:
        stocks = await em.search_stocks("600")
    assert [s.secucode for s in stocks] == ["600519.SH", "000001.SZ"]
    assert stocks[0].secid == "1.600519"
    assert stocks[1].secid == "0.000001"
    assert stocks[0].name == "贵州茅台"


@pytest.mark.asyncio
async def test_search_stocks_filters_non_a_share(respx_mock):
    respx_mock.get("https://searchapi.eastmoney.com/api/suggest/get").mock(
        return_value=httpx.Response(
            200,
            json={"QuotationCodeTable": {"Data": [
                {"Code": "600519", "Name": "贵州茅台", "MktNum": "1"},
                {"Code": "00700", "Name": "腾讯控股", "MktNum": "116"},  # 港股：5 位代码
                {"Code": "1A0001", "Name": "上证指数", "MktNum": "1"},  # 指数：非纯数字
                {"Code": "600600", "Name": "某境外", "MktNum": "116"},  # 6 位但市场非 A 股
            ]}},
        )
    )
    async with EastMoneyClient() as em:
        stocks = await em.search_stocks("600")
    assert [s.secucode for s in stocks] == ["600519.SH"]


@pytest.mark.asyncio
async def test_search_stocks_empty_when_no_data(respx_mock):
    respx_mock.get("https://searchapi.eastmoney.com/api/suggest/get").mock(
        return_value=httpx.Response(200, json={"QuotationCodeTable": {"Data": None}})
    )
    async with EastMoneyClient() as em:
        stocks = await em.search_stocks("xxx")
    assert stocks == []


@pytest.mark.asyncio
async def test_fetch_float_shares_parses_f85(respx_mock):
    respx_mock.get("https://push2.eastmoney.com/api/qt/stock/get").mock(
        return_value=httpx.Response(200, json={"data": {"f85": 20628944429}})
    )
    async with EastMoneyClient() as em:
        fs = await em.fetch_float_shares("1.600036")
    assert fs == 20628944429


@pytest.mark.asyncio
async def test_fetch_float_shares_zero_when_no_data(respx_mock):
    respx_mock.get("https://push2.eastmoney.com/api/qt/stock/get").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with EastMoneyClient() as em:
        fs = await em.fetch_float_shares("1.600036")
    assert fs == 0.0
