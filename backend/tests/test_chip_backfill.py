"""自选股筹码补全：parse_days / 进程内状态 / 编排主流程测试。"""
import pytest

from app.services.chip_backfill import (
    ALL_DAYS,
    parse_days,
    get_backfill_status,
    set_backfill_status,
    is_backfill_running,
    set_backfill_running,
    reset_backfill_state,
)


def test_parse_days_all():
    assert parse_days("all") == ALL_DAYS


def test_parse_days_numeric():
    assert parse_days("120") == 120
    assert parse_days("365") == 365


def test_parse_days_invalid():
    with pytest.raises(ValueError):
        parse_days("999")
    with pytest.raises(ValueError):
        parse_days("")


def test_state_get_set_reset():
    reset_backfill_state()
    assert get_backfill_status() is None
    assert is_backfill_running() is False
    set_backfill_running(True)
    assert is_backfill_running() is True
    set_backfill_status({"state": "running", "window": "365"})
    assert get_backfill_status() == {"state": "running", "window": "365"}
    reset_backfill_state()
    assert get_backfill_status() is None
    assert is_backfill_running() is False


from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.base import Base
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.services import chip_backfill


@pytest.mark.asyncio
async def test_backfill_watchlist_chips_main_flow(monkeypatch):
    """遍历 watchlist 逐只 ingest：第 2 只抛错计 failed，on_progress 末次为完成态。"""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "TRUNCATE stock_meta, watchlist, daily_kline, chip_distribution CASCADE"
        ))
    async with factory() as s:
        s.add_all([
            StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                      market="SH", secid="1.600519"),
            StockMeta(secucode="000001.SZ", code="000001", name="平安银行",
                      market="SZ", secid="0.000001"),
            Watchlist(secucode="600519.SH", scope="default", sort_order=0),
            Watchlist(secucode="000001.SZ", scope="default", sort_order=1),
        ])
        await s.commit()

    calls = []

    async def fake_ingest(tdx, em, session, secucode, secid, *, days):
        calls.append((secucode, days))
        if secucode == "000001.SZ":
            raise RuntimeError("boom")
        return {"klines": 3, "chips": 3}

    monkeypatch.setattr(chip_backfill, "ingest_kline_and_chips", fake_ingest)

    progress = []
    result = await chip_backfill.backfill_watchlist_chips(
        factory, tdx=None, em=None, days=365,
        on_progress=lambda done, total, ok, failed: progress.append((done, total, ok, failed)),
    )

    assert result == {"total": 2, "ok": 1, "failed": 1}
    assert calls == [("600519.SH", 365), ("000001.SZ", 365)]
    assert progress[-1] == (2, 2, 1, 1)  # 末次进度为完成态
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_watchlist_empty(monkeypatch):
    """watchlist 为空 → total=0，正常完成（非错误）。"""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, watchlist CASCADE"))

    async def _never(*a, **kw):
        pytest.fail("空 watchlist 不应调用 ingest")

    monkeypatch.setattr(chip_backfill, "ingest_kline_and_chips", _never)
    result = await chip_backfill.backfill_watchlist_chips(factory, None, None, days=120)
    assert result == {"total": 0, "ok": 0, "failed": 0}
    await engine.dispose()
