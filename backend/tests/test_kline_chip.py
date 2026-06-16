"""kline_chip 编排层 + watchlist 采集触发的测试。"""
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.chip import ChipDistribution
from app.models.holder import HolderSummary
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.types import StockInfo
from app.services.ingest import upsert_stock_meta
from app.services.kline_chip import ingest_kline_and_chips, resolve_decay_coeff, resolve_float_shares
from app.utils.time import trading_day_ts

_META = [StockInfo("600519.SH", "600519", "贵州茅台", "SH", "1.600519")]
_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_SAMPLES = [
    "2026-06-11,1680.00,1685.00,1690.00,1675.00,10000,1683000000,0.89,0.30,5.0,0.8",
    "2026-06-12,1685.00,1690.00,1695.00,1680.00,12000,2028000000,0.89,0.30,5.0,0.9",
    "2026-06-13,1690.00,1688.00,1698.00,1685.00,8000,1350400000,0.89,-0.12,2.0,0.6",
]


@pytest.mark.asyncio
async def test_resolve_decay_defaults_when_no_holder(db_session):
    """无 holder_summary → 返回 settings.chip_decay_default（2.0）。"""
    decay = await resolve_decay_coeff(db_session, "600519.SH")
    assert decay == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_resolve_decay_uses_holder_when_available(db_session):
    """有最新 holder_summary → 返回其 decay_coeff（3.5）。"""
    db_session.add(HolderSummary(
        ts=trading_day_ts("2026-06-13"),
        secucode="600519.SH",
        top10_ratio=30.0,
        decay_coeff=3.5,
        float_shares=1_000_000,
    ))
    await db_session.commit()
    decay = await resolve_decay_coeff(db_session, "600519.SH")
    assert decay == pytest.approx(3.5)


@pytest.mark.asyncio
async def test_ingest_empty_kline_skips_chips(db_session, respx_mock):
    """东财返回空（新股/停牌）→ 返回 {klines:0, chips:0}，不抛异常。"""
    respx_mock.get(_KLINE_URL).mock(return_value=httpx.Response(200, json={"data": None}))
    await upsert_stock_meta(db_session, _META)
    async with EastMoneyClient() as em:
        r = await ingest_kline_and_chips(em, db_session, "600519.SH", "1.600519", days=30)
    assert r == {"klines": 0, "chips": 0}


@pytest.mark.asyncio
async def test_ingest_kline_and_chips_end_to_end(db_session, respx_mock):
    """mock 3 根日K → daily_kline、chip_distribution 各 3 行，返回 {klines:3, chips:3}。"""
    respx_mock.get(_KLINE_URL).mock(
        return_value=httpx.Response(200, json={"data": {"klines": _SAMPLES}})
    )
    await upsert_stock_meta(db_session, _META)
    async with EastMoneyClient() as em:
        r = await ingest_kline_and_chips(em, db_session, "600519.SH", "1.600519", days=30)
    assert r == {"klines": 3, "chips": 3}
    klines = (
        await db_session.execute(
            select(DailyKline)
            .where(DailyKline.secucode == "600519.SH")
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    chips = (
        await db_session.execute(
            select(ChipDistribution)
            .where(ChipDistribution.secucode == "600519.SH")
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert len(klines) == 3
    assert len(chips) == 3


@pytest_asyncio.fixture
async def kline_chip_client():
    """API 客户端：override get_db，seed stock_meta，TRUNCATE 含 daily_kline/chip_distribution。"""
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE stock_meta, daily_kline, chip_distribution, holder_summary, watchlist CASCADE"
        ))
    async with SessionLocal() as s:
        s.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                        market="SH", secid="1.600519", industry="白酒"))
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
            "TRUNCATE stock_meta, daily_kline, chip_distribution, holder_summary, watchlist CASCADE"
        ))
    await engine.dispose()


async def _count_rows(model, secucode: str) -> int:
    """独立 session 抽查某 secucode 的行数（API 已 commit 到同一 DB）。"""
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            rows = (
                await s.execute(select(model).where(model.secucode == secucode))
            ).scalars().all()
        return len(rows)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_add_watchlist_triggers_ingest(kline_chip_client, respx_mock):
    """POST /api/watchlist → 触发采集，daily_kline/chip_distribution 各落 3 行。"""
    respx_mock.get(_KLINE_URL).mock(
        return_value=httpx.Response(200, json={"data": {"klines": _SAMPLES}})
    )
    r = await kline_chip_client.post("/api/watchlist", json={"secucode": "600519.SH"})
    assert r.status_code == 201
    assert await _count_rows(DailyKline, "600519.SH") == 3
    assert await _count_rows(ChipDistribution, "600519.SH") == 3


@pytest.mark.asyncio
async def test_add_watchlist_ingest_failure_does_not_rollback(kline_chip_client, respx_mock):
    """采集抛异常（限流/网络）→ POST 仍 201，watchlist 行已落库（容错边界）。"""
    respx_mock.get(_KLINE_URL).mock(side_effect=httpx.ConnectError("rate limited"))
    r = await kline_chip_client.post("/api/watchlist", json={"secucode": "600519.SH"})
    assert r.status_code == 201
    assert await _count_rows(Watchlist, "600519.SH") == 1


@pytest.mark.asyncio
async def test_resolve_float_shares_uses_cache(db_session):
    """stock_meta.float_shares 已缓存 → 直接返回，不请求东财。"""
    db_session.add(StockMeta(secucode="600036.SH", code="600036", name="招商银行",
                             market="SH", secid="1.600036", float_shares=2_000_000_000))
    await db_session.commit()
    fs = await resolve_float_shares(db_session, em=None, secucode="600036.SH", secid="1.600036")
    assert fs == 2_000_000_000


@pytest.mark.asyncio
async def test_resolve_float_shares_fetches_and_caches(db_session, respx_mock):
    """缓存缺失 → 东财取 → 回填 stock_meta.float_shares。"""
    db_session.add(StockMeta(secucode="600036.SH", code="600036", name="招商银行",
                             market="SH", secid="1.600036"))  # float_shares=None
    await db_session.commit()
    respx_mock.get("https://push2.eastmoney.com/api/qt/stock/get").mock(
        return_value=httpx.Response(200, json={"data": {"f85": 20_628_944_429}})
    )
    async with EastMoneyClient() as em:
        fs = await resolve_float_shares(db_session, em, "600036.SH", "1.600036")
    assert fs == 20_628_944_429
    # 回填确认
    cached = (
        await db_session.execute(
            select(StockMeta.float_shares).where(StockMeta.secucode == "600036.SH")
        )
    ).scalar_one()
    assert float(cached) == 20_628_944_429
