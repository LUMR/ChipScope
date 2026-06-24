"""Task 7: 选股筛选器 API 集成测试。

注：本测试不依赖 conftest.db_session，而是仿 test_api_watchlist::watchlist_client
建立独立 engine + dependency_overrides[get_db]——否则 ASGI app 默认 get_db 会读到模块级
SessionLocal（连测试库但 schema 可能漂移），与 fixture engine 的事务隔离，
数据进不去。这是项目既有的跨 event-loop 连接坑。

选股信号语义（见 indicator.py）：MACD 看趋势方向，KDJ/WR/RSI 视超买为空、超卖为多。
因此纯单边上涨→超买→bull/bear；纯下跌→超卖→bull；long-up+sharp-crash→DIF 仍 >0
但 wr/rsi/kdj 全超卖→strong_bull。测试 fixture 据此构造，不依赖“涨=多”的直觉。
"""
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.base import Base
from app.models.kline import DailyKline
from app.models.stock import StockMeta


def _strong_bull_series() -> list[float]:
    """50 根缓涨 + 10 根急跌 → DIF>0 但 wr/rsi/kdj 超卖 → strong_bull (score=3)。"""
    out = []
    base = 100.0
    for i in range(50):
        out.append(base + i * 1.2)
    peak = out[-1]
    for i in range(1, 11):
        out.append(peak - i * 2.0)
    return out


def _bull_series() -> list[float]:
    """纯单边下跌（绿柱）→ 超卖 → bull (score=2)。与 strong_bull 信号不同。"""
    return [100.0 - i for i in range(60)]


async def _seed(session, code: str, name: str, closes: list[float], green: bool = True):
    suf = "SH" if code.startswith("6") else "SZ"
    secid = f"{'1' if suf == 'SH' else '0'}.{code}"
    secucode = f"{code}.{suf}"
    session.add(StockMeta(secucode=secucode, code=code, name=name,
                          market=suf, secid=secid))
    await session.commit()
    for i, c in enumerate(closes):
        session.add(DailyKline(
            ts=date(2026, 4, 1) + timedelta(days=i),  # 60 根，含周末无碍，仅做主键
            secucode=secucode,
            open=c, close=c,
            high=c * 1.01, low=c * 0.99,
            volume=1000, amount=c * 100000,
            turnover_rate=0.0, pct_change=0.5 if green else -0.5, vwap=c,
        ))
    await session.commit()


@pytest_asyncio.fixture
async def screener_client():
    """独立 engine + dependency_overrides，对齐 test_api_watchlist 模式。"""
    from app.api.deps import get_db
    from app.main import app

    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, daily_kline CASCADE"))

    async with SessionLocal() as s:
        await _seed(s, "600519", "贵州茅台", _strong_bull_series(), green=True)
        await _seed(s, "000001", "平安银行", _bull_series(), green=False)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stock_meta, daily_kline CASCADE"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_screener_filters_strong_bull(screener_client):
    r = await screener_client.post("/api/screener", json={"signal": "strong_bull"})
    assert r.status_code == 200, r.text
    data = r.json()
    codes = [d["secucode"] for d in data]
    assert "600519.SH" in codes
    assert "000001.SZ" not in codes  # 平安银行为 bull，被过滤
    hit = next(d for d in data if d["secucode"] == "600519.SH")
    assert hit["score"] >= 3
    assert hit["signal"] == "strong_bull"
    assert hit["name"] == "贵州茅台"
    # 返回项必须包含四大指标
    assert set(hit) >= {"macd", "kdj", "wr", "rsi", "close", "pct"}


@pytest.mark.asyncio
async def test_screener_filters_bull(screener_client):
    r = await screener_client.post("/api/screener", json={"signal": "bull"})
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
    assert set(codes) == {"600519.SH", "000001.SZ"}
    # score_desc：strong_bull(3) 排在 bull(2) 前
    assert codes[0] == "600519.SH"
