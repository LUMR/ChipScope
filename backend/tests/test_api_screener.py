"""选股筛选器 API 集成测试（阶段2：查 stock_metric 物化表）。

注：本测试不依赖 conftest.db_session，而是仿 test_api_watchlist::watchlist_client
建立独立 engine + dependency_overrides[get_db]。
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


def _metric(secucode: str, score: int, signal: str,
            macd: int, kdj: int, wr: int, rsi: int,
            close: float = 104.0, pct: float = 1.2, **overrides) -> dict:
    """构造一条 stock_metric 行。默认多头排列（ma5>ma10>ma20>ma60、close 居上、
    high20/60_prev 居下），extras 默认全部可通过。"""
    row = {
        "trade_date": date(2026, 6, 24), "secucode": secucode,
        "close": close, "open": close * 0.99, "dif": 1.0, "dea": 0.5, "hist": 1.0,
        "k": 50.0, "d": 48.0, "j": 54.0, "wr": 60.0, "rsi": 55.0, "prev_rsi": 52.0,
        "ma5": 103.0, "ma10": 102.0, "ma20": 101.0, "ma60": 100.0,
        "ma20_prev5": 100.0, "high20_prev": 99.0, "high60_prev": 98.0,
        "vol_ratio": 2.5, "pct5": 8.0, "consecutive_green": 4, "pct_change": pct,
        "score": score, "signal_level": signal,
        "macd_signal": macd, "kdj_signal": kdj, "wr_signal": wr, "rsi_signal": rsi,
    }
    row.update(overrides)
    return row


async def _seed_metric(session, secucode: str, name: str, **kw):
    code = secucode.split(".")[0]
    suf = secucode.split(".")[1]
    secid = f"{'1' if suf == 'SH' else '0'}.{code}"
    session.add(StockMeta(secucode=secucode, code=code, name=name, market=suf, secid=secid))
    session.add(StockMetric(**_metric(secucode, **kw)))
    await session.commit()


@pytest_asyncio.fixture
async def screener_client():
    """独立 engine + dependency_overrides。"""
    from app.api.deps import get_db
    from app.main import app

    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, stock_metric CASCADE"))

    async with SessionLocal() as s:
        await _seed_metric(s, "600519.SH", "贵州茅台",
                           score=4, signal="strong_bull", macd=1, kdj=1, wr=1, rsi=1)
        await _seed_metric(s, "000001.SZ", "平安银行",
                           score=-3, signal="strong_bear", macd=-1, kdj=-1, wr=-1, rsi=-1)
        # 次新股：30–59 根时 ma60 物化为 NULL
        await _seed_metric(s, "601999.SH", "次新股",
                           score=4, signal="strong_bull", macd=1, kdj=1, wr=1, rsi=1,
                           ma60=None)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stock_meta, stock_metric CASCADE"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_screener_filters_strong_bull(screener_client):
    r = await screener_client.post("/api/screener", json={"signal": "strong_bull"})
    assert r.status_code == 200, r.text
    data = r.json()
    codes = [d["secucode"] for d in data]
    assert "600519.SH" in codes
    assert "601999.SH" in codes   # NULL ma60 不影响 signal 过滤
    assert "000001.SZ" not in codes
    hit = next(d for d in data if d["secucode"] == "600519.SH")
    assert hit["score"] >= 3
    assert hit["signal"] == "strong_bull"
    assert hit["name"] == "贵州茅台"
    assert set(hit) >= {"macd", "kdj", "wr", "rsi", "close", "pct"}


@pytest.mark.asyncio
async def test_screener_filters_strong_bear(screener_client):
    r = await screener_client.post("/api/screener", json={"signal": "strong_bear"})
    assert r.status_code == 200, r.text
    data = r.json()
    codes = [d["secucode"] for d in data]
    assert "000001.SZ" in codes
    assert "600519.SH" not in codes


@pytest.mark.asyncio
async def test_screener_no_signal_returns_all_sorted(screener_client):
    r = await screener_client.post("/api/screener", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    codes = [d["secucode"] for d in data]
    assert set(codes) == {"600519.SH", "601999.SH", "000001.SZ"}
    # score_desc：strong_bull(4) 的两只排在 strong_bear(-3) 前；同分 4 的二者顺序不定
    assert codes[-1] == "000001.SZ"
    assert codes[0] in {"600519.SH", "601999.SH"}


@pytest.mark.asyncio
async def test_screener_empty_when_no_metrics():
    """表空 → 返回空列表（不崩）。"""
    from app.api.deps import get_db
    from app.main import app

    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, stock_metric CASCADE"))

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/screener", json={"signal": "strong_bull"})
    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_screener_volume_up_extra(screener_client):
    """vol_ratio=2.5 > k=2.0 → 通过 volume_up。"""
    r = await screener_client.post("/api/screener", json={
        "signal": "strong_bull",
        "extras": [{"type": "volume_up"}],
    })
    assert r.status_code == 200
    assert any(d["secucode"] == "600519.SH" for d in r.json())


@pytest.mark.asyncio
async def test_screener_null_ma60_excluded_from_ma_bull(screener_client):
    """ma60 为 NULL（次新股）→ NaN 比较 False → ma_bull 过滤掉；正常股通过。"""
    r = await screener_client.post("/api/screener", json={
        "signal": "strong_bull",
        "extras": [{"type": "ma_bull"}],
    })
    assert r.status_code == 200
    codes = [d["secucode"] for d in r.json()]
    assert "600519.SH" in codes
    assert "601999.SH" not in codes
