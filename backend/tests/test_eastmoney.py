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
                {"Code": "600519", "Name": "贵州茅台", "MktNum": "1", "SecurityType": "1"},
                {"Code": "000001", "Name": "平安银行", "MktNum": "0", "SecurityType": "2"},
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
                {"Code": "600519", "Name": "贵州茅台", "MktNum": "1", "SecurityType": "1"},   # 沪A
                {"Code": "00700", "Name": "腾讯控股", "MktNum": "116", "SecurityType": "19"}, # 港股
                {"Code": "1A0001", "Name": "上证指数", "MktNum": "1", "SecurityType": "5"},   # 指数
                {"Code": "600600", "Name": "某境外", "MktNum": "116", "SecurityType": "19"},  # 港股
            ]}},
        )
    )
    async with EastMoneyClient() as em:
        stocks = await em.search_stocks("600")
    assert [s.secucode for s in stocks] == ["600519.SH"]


@pytest.mark.asyncio
async def test_search_stocks_filters_bonds_keeps_a_shares(respx_mock):
    """仅留沪深 A 股 + 科创板，过滤债券/ETF 等同名品种。

    东财 SecurityType 真实值：1=沪A, 2=深A(含创业板), 25=科创板；16=债券, 8=ETF。
    回归 1：搜"交通银行"时其金融债（SecurityType=16）曾因「6位数字+MktNum=1」绕过过滤。
    回归 2：过滤曾误写为 (2,25) 漏掉沪A（1），导致沪市 A 股全部被滤、搜索返回空。
    """
    respx_mock.get("https://searchapi.eastmoney.com/api/suggest/get").mock(
        return_value=httpx.Response(
            200,
            json={"QuotationCodeTable": {"Data": [
                {"Code": "601328", "Name": "交通银行", "MktNum": "1", "SecurityType": "1"},    # 沪A
                {"Code": "751087", "Name": "交通银行", "MktNum": "1", "SecurityType": "16"},   # 债券（须过滤）
                {"Code": "159666", "Name": "交运ETF华夏", "MktNum": "0", "SecurityType": "8"}, # ETF（须过滤）
                {"Code": "688981", "Name": "中芯国际", "MktNum": "1", "SecurityType": "25"},   # 科创板
                {"Code": "000001", "Name": "平安银行", "MktNum": "0", "SecurityType": "2"},    # 深A
            ]}},
        )
    )
    async with EastMoneyClient() as em:
        stocks = await em.search_stocks("交通银行")
    assert [s.secucode for s in stocks] == ["601328.SH", "688981.SH", "000001.SZ"]


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
