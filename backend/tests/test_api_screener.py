"""Task 4: 选股筛选器 API 集成测试（stock_metric 物化表版本）。

不再 seed daily_kline 实时算指标，而是 seed 预计算好的 stock_metric 行，
screener 改为查最新 trade_date 的物化行 → signal/extras 过滤 → score 排序。

fixture 沿用 test_api_stocks.py::api_client 的 proven 模式（独立 engine +
drop_all/create_all + dependency_overrides[get_db]），而非 conftest.db_session +
裸 ASGITransport——后者在 asyncio_mode=function 的跨 event loop 下会触发模块级
SessionLocal 连接池中毒（"None.send"/"Event loop is closed"）。
"""
from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.base import Base
from app.models.stock import StockMeta
from app.models.stock_metric import StockMetric


def _metric(score, signal, macd, kdj, wr, rsi, close=100, pct=1.2):
    """组装一行 stock_metric 的字段（除 trade_date / secucode 外）。

    默认值满足常见 extras：vol_ratio=2.5 > volume_up k=2.0、pct5=8 在 pct_range[3,15]、
    consecutive_green=4、ma 多头排列、ma20 上行（ma20==ma20_prev5 触发 ma_up 视配置而定）。
    """
    return {
        "close": close, "open": close * 0.99, "dif": 1.0, "dea": 0.5, "hist": 1.0,
        "k": 50.0, "d": 48.0, "j": 54.0, "wr": 60.0, "rsi": 55.0, "prev_rsi": 52.0,
        "ma5": close, "ma10": close, "ma20": close, "ma60": close,
        "ma20_prev5": close, "high20_prev": close, "high60_prev": close,
        "vol_ratio": 2.5, "pct5": 8.0, "consecutive_green": 4, "pct_change": pct,
        "score": score, "signal_level": signal,
        "macd_signal": macd, "kdj_signal": kdj, "wr_signal": wr, "rsi_signal": rsi,
    }


async def _seed_metric(session, secucode, name, trade_date, **kw):
    """单 session 内加 StockMeta + StockMetric 后一次 commit。

    SQLAlchemy unit-of-work 按 FK 依赖顺序 flush，StockMeta 先于 StockMetric，
    因此单 commit 即可。若遇到 FK 顺序问题，可改为先 commit StockMeta。
    """
    session.add(StockMeta(
        secucode=secucode, code=secucode.split(".")[0], name=name,
        market=secucode.split(".")[1],
        secid=f"{'1' if secucode.endswith('SH') else '0'}.{secucode.split('.')[0]}",
    ))
    session.add(StockMetric(trade_date=trade_date, secucode=secucode,
                            **_metric(**kw)))
    await session.commit()


@pytest_asyncio.fixture
async def metric_client():
    """自包含 client：独立 engine + drop_all/create_all + dependency_overrides[get_db]。

    返回 (client, SessionLocal)，测试体可经 SessionLocal 在 fixture engine 上
    追加 seed 数据（不走 ASGI）。
    """
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, stock_metric CASCADE"))

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
        await conn.execute(text("TRUNCATE stock_meta, stock_metric CASCADE"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_screener_filters_strong_bull(metric_client):
    """signal=strong_bull 只返回 strong_bull 行；返回项含四大指标信号。"""
    client, SessionLocal = metric_client
    async with SessionLocal() as s:
        await _seed_metric(s, "600519.SH", "贵州茅台", date(2026, 6, 24),
                           score=4, signal="strong_bull", macd=1, kdj=1, wr=1, rsi=1)
        await _seed_metric(s, "000001.SZ", "平安银行", date(2026, 6, 24),
                           score=-3, signal="strong_bear", macd=-1, kdj=-1, wr=-1, rsi=-1)
    r = await client.post("/api/screener", json={"signal": "strong_bull"})
    assert r.status_code == 200, r.text
    data = r.json()
    codes = [d["secucode"] for d in data]
    assert "600519.SH" in codes
    assert "000001.SZ" not in codes  # strong_bear 被过滤
    hit = next(d for d in data if d["secucode"] == "600519.SH")
    assert hit["score"] >= 3
    assert hit["signal"] == "strong_bull"
    assert hit["name"] == "贵州茅台"
    # 返回项必须包含四大指标 + close/pct
    assert set(hit) >= {"macd", "kdj", "wr", "rsi", "close", "pct"}


@pytest.mark.asyncio
async def test_screener_empty_when_no_metrics(metric_client):
    """stock_metric 无数据 → latest is None → 空列表。"""
    client, _ = metric_client
    r = await client.post("/api/screener", json={"signal": "strong_bull"})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_screener_volume_up_extra(metric_client):
    """extras volume_up k=2.0：vol_ratio=2.5 > 2.0 → 通过。"""
    client, SessionLocal = metric_client
    async with SessionLocal() as s:
        await _seed_metric(s, "600519.SH", "贵州茅台", date(2026, 6, 24),
                           score=4, signal="strong_bull", macd=1, kdj=1, wr=1, rsi=1)
    r = await client.post("/api/screener", json={
        "signal": "strong_bull", "extras": [{"type": "volume_up"}]})
    assert r.status_code == 200, r.text
    assert any(d["secucode"] == "600519.SH" for d in r.json())
