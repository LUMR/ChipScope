import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.flow import MoneyFlow
from app.models.holder import TopHolder
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.types import StockInfo
from app.utils.time import trading_day_ts


@pytest.fixture
def sample_stocks():
    return [
        StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                  market="SH", secid="1.600519"),
        StockMeta(secucode="000001.SZ", code="000001", name="平安银行",
                  market="SZ", secid="0.000001"),
    ]


@pytest.fixture
def sample_klines():
    return [DailyKline(
        ts=trading_day_ts("2026-06-13"), secucode="600519.SH",
        open=1680, close=1685, high=1690, low=1675,
        volume=10000, amount=1.683e9, turnover_rate=0.8,
        pct_change=0.3, vwap=1683.0,
    )]


@pytest.fixture
def sample_holders():
    return [TopHolder(
        ts=trading_day_ts("2026-03-31"), secucode="600519.SH", rank=1,
        holder_name="香港中央结算", hold_num=1000000, hold_ratio=5.5,
        change_num=-10000, holder_type=None,
    )]


@pytest.fixture
def sample_flows():
    return [MoneyFlow(
        ts=trading_day_ts("2026-06-13"), secucode="600519.SH",
        main_net=1e8, super_large_net=5e7, large_net=3e7,
        medium_net=-1e7, small_net=-7e7,
    )]


@pytest_asyncio.fixture
async def api_client(sample_stocks, sample_klines, sample_holders, sample_flows):
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE stock_meta, daily_kline, top_holders, holder_summary, money_flow CASCADE"
        ))
    async with SessionLocal() as s:
        s.add_all(sample_stocks)
        await s.commit()
        s.add_all(sample_klines)
        await s.commit()
        s.add_all(sample_holders)
        await s.commit()
        s.add_all(sample_flows)
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
            "TRUNCATE stock_meta, daily_kline, top_holders, holder_summary, money_flow CASCADE"
        ))
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_stocks_no_filter(api_client):
    r = await api_client.get("/api/stocks")
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_list_stocks_search_by_code(api_client, monkeypatch):
    """q 走东财：返回东财结果（含本地没有的股票）。"""
    async def fake_search(self, q, count=10):
        assert q == "600036"
        return [StockInfo("600036.SH", "600036", "招商银行", "SH", "1.600036")]
    monkeypatch.setattr(EastMoneyClient, "search_stocks", fake_search)
    r = await api_client.get("/api/stocks", params={"q": "600036"})
    data = r.json()
    assert len(data) == 1 and data[0]["secucode"] == "600036.SH"


@pytest.mark.asyncio
async def test_list_stocks_search_by_name(api_client, monkeypatch):
    async def fake_search(self, q, count=10):
        return [StockInfo("000333.SZ", "000333", "美的集团", "SZ", "0.000333")]
    monkeypatch.setattr(EastMoneyClient, "search_stocks", fake_search)
    r = await api_client.get("/api/stocks", params={"q": "美的"})
    data = r.json()
    assert len(data) == 1 and data[0]["name"] == "美的集团"


@pytest.mark.asyncio
async def test_list_stocks_q_calls_eastmoney(api_client, monkeypatch):
    """q 非空时确实调用了东财 search_stocks（而非查本地）。"""
    calls = []

    async def fake_search(self, q, count=10):
        calls.append(q)
        return []

    monkeypatch.setattr(EastMoneyClient, "search_stocks", fake_search)
    await api_client.get("/api/stocks", params={"q": "茅台"})
    assert calls == ["茅台"]


@pytest.mark.asyncio
async def test_get_kline_returns_bars(api_client):
    r = await api_client.get("/api/stocks/600519.SH/kline")
    data = r.json()
    assert len(data) == 1 and data[0]["close"] == 1685.0


@pytest.mark.asyncio
async def test_get_holders(api_client):
    r = await api_client.get("/api/stocks/600519.SH/holders")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["holder_name"] == "香港中央结算"
    assert float(data[0]["hold_ratio"]) == 5.5


@pytest.mark.asyncio
async def test_get_flow(api_client):
    r = await api_client.get("/api/stocks/600519.SH/flow")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert float(data[0]["main_net"]) == 1e8


@pytest_asyncio.fixture
async def indicators_client():
    """Task 5: 自包含 client——独立 engine + dependency_overrides[get_db]。

    不复用 conftest.db_session：ASGI app 默认 get_db 走模块级 SessionLocal（连测试库
    但跨 event loop 复用连接，Windows ProactorEventLoop 下报 "Event loop is closed"）。
    仿 test_api_watchlist::watchlist_client / test_api_screener 用 override 注入测试 session。

    仅 seed 两只 StockMeta 父记录（600519.SH 供指标用例 + 000001.SZ 供 404 用例）；
    yield (client, SessionLocal)，各用例自行 seed stock_metric 或 daily_kline。
    """
    from app.models.base import Base

    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE stock_meta, daily_kline, top_holders, holder_summary, money_flow, "
            "stock_metric CASCADE"
        ))
    async with SessionLocal() as s:
        s.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                        market="SH", secid="1.600519"))
        s.add(StockMeta(secucode="000001.SZ", code="000001", name="平安银行",
                        market="SZ", secid="0.000001"))
        await s.commit()

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    from app.api.deps import get_db
    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, SessionLocal

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE stock_meta, daily_kline, top_holders, holder_summary, money_flow, "
            "stock_metric CASCADE"
        ))
    await engine.dispose()


@pytest.mark.asyncio
async def test_stock_indicators_from_metric(indicators_client):
    """GET /{secucode}/indicators：优先查 stock_metric 时序（>= count 行）。"""
    from datetime import date, timedelta

    from app.models.stock_metric import StockMetric

    client, SessionLocal = indicators_client
    # seed 60 行 stock_metric（valid 日期：2026-01-01 起 60 天）
    async with SessionLocal() as s:
        for i in range(60):
            s.add(StockMetric(
                trade_date=date(2026, 1, 1) + timedelta(days=i), secucode="600519.SH",
                close=100 + i, open=100 + i, dif=1.0, dea=0.5, hist=1.0,
                k=50.0, d=48.0, j=54.0, wr=60.0, rsi=55.0, prev_rsi=52.0,
                ma5=100.0, ma10=100.0, ma20=100.0, ma60=100.0, ma20_prev5=100.0,
                high20_prev=100.0, high60_prev=100.0, vol_ratio=1.0, pct5=1.0,
                consecutive_green=1, pct_change=1.0,
                score=2, signal_level="bull",
                macd_signal=1, kdj_signal=1, wr_signal=0, rsi_signal=0,
            ))
        await s.commit()
    r = await client.get("/api/stocks/600519.SH/indicators?count=60")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 60
    # 升序（最早在前）：第一根 close=100，最后一根 close=159
    assert float(data[0]["close"]) == 100.0
    assert float(data[-1]["close"]) == 159.0
    assert set(data[-1]) >= {"date", "dif", "dea", "hist", "k", "d", "j", "wr", "rsi", "close"}


@pytest.mark.asyncio
async def test_stock_indicators_fallback_realtime(indicators_client):
    """stock_metric 不足 → 回退实时算（读 daily_kline）。"""
    from datetime import date, timedelta

    client, SessionLocal = indicators_client
    # 无 stock_metric；seed 60 行 daily_kline（valid 日期）
    dates_in = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(60)]
    async with SessionLocal() as s:
        for ds in dates_in:
            s.add(DailyKline(ts=trading_day_ts(ds), secucode="600519.SH",
                             open=100, close=100, high=101, low=99, volume=1000,
                             amount=1e7, turnover_rate=0, pct_change=1.0, vwap=100))
        await s.commit()
    r = await client.get("/api/stocks/600519.SH/indicators?count=60")
    assert r.status_code == 200
    assert len(r.json()) == 60  # 回退实时算给满 60 根


@pytest.mark.asyncio
async def test_stock_indicators_404_when_no_data(indicators_client):
    """无 stock_metric 且无 daily_kline：返回 404。"""
    client, _ = indicators_client
    r = await client.get("/api/stocks/000001.SZ/indicators?count=60")
    assert r.status_code == 404
