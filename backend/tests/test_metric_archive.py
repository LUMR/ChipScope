import pytest
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.base import Base
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.models.stock_metric import StockMetric
from app.services.collector.types import StockInfo
from app.services.ingest import upsert_stock_meta, upsert_stock_metric


@pytest.mark.asyncio
async def test_upsert_stock_metric_inserts_and_updates(db_session):
    # stock_metric 有 FK 到 stock_meta，先建元数据（仿 test_ingest 的 daily_kline 用例）
    await upsert_stock_meta(
        db_session,
        [StockInfo("600519.SH", "600519", "贵州茅台", "SH", "1.600519")],
    )
    row = {
        "trade_date": date(2026, 6, 24), "secucode": "600519.SH",
        "close": 1680.0, "open": 1670.0, "dif": 1.0, "dea": 0.5, "hist": 1.0,
        "k": 50.0, "d": 48.0, "j": 54.0, "wr": 60.0, "rsi": 55.0, "prev_rsi": 52.0,
        "ma5": 1670.0, "ma10": 1660.0, "ma20": 1650.0, "ma60": 1600.0,
        "ma20_prev5": 1620.0, "high20_prev": 1660.0, "high60_prev": 1640.0,
        "vol_ratio": 1.5, "pct5": 3.0, "consecutive_green": 2,
        "pct_change": 1.2,
        "score": 4, "signal_level": "strong_bull",
        "macd_signal": 1, "kdj_signal": 1, "wr_signal": 1, "rsi_signal": 1,
    }
    n = await upsert_stock_metric(db_session, [row])
    assert n == 1
    got = (await db_session.execute(
        select(StockMetric).where(StockMetric.secucode == "600519.SH")
        .execution_options(populate_existing=True)
    )).scalars().one()
    assert got.score == 4 and got.signal_level == "strong_bull"

    # 幂等 update：同 PK 再写，score 改变
    row["score"] = 0
    row["signal_level"] = "neutral"
    await upsert_stock_metric(db_session, [row])
    got2 = (await db_session.execute(
        select(StockMetric).where(StockMetric.secucode == "600519.SH")
        .execution_options(populate_existing=True)
    )).scalars().one()
    assert got2.score == 0 and got2.signal_level == "neutral"


def _strong_bull_series() -> list[float]:
    """50 根缓涨 + 10 根急跌 → DIF>0 但 wr/rsi/kdj 超卖 → strong_bull (score=3)。"""
    out: list[float] = []
    base = 100.0
    for i in range(50):
        out.append(base + i * 1.2)
    peak = out[-1]
    for i in range(1, 11):
        out.append(peak - i * 2.0)
    return out


@pytest.mark.asyncio
async def test_archive_daily_metrics_computes_and_upserts(db_session):
    """archive_daily_metrics：读 daily_kline → compute_indicators → upsert stock_metric。
    seed 50 缓涨 + 10 急跌构造 strong_bull；trade_date 取 2026-12-31 覆盖全部 60 根。"""
    from app.services.metric_archive import (
        archive_daily_metrics, reset_metrics_archive_state,
    )

    # 独立 engine + factory（仿 test_kline_archive 模式，避免跨 session 刷新问题）
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, daily_kline, stock_metric CASCADE"))

    # seed：茅台 60 根（50 缓涨 + 10 急跌）→ strong_bull；合法日期用 timedelta
    # 先 commit StockMeta（满足 FK），再加 DailyKline
    closes = _strong_bull_series()
    async with factory() as s:
        s.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                        market="SH", secid="1.600519"))
        await s.commit()
    async with factory() as s:
        for i, c in enumerate(closes):
            s.add(DailyKline(
                ts=datetime(2026, 4, 1, tzinfo=timezone.utc) + timedelta(days=i),
                secucode="600519.SH", open=c, close=c, high=c * 1.01, low=c * 0.99,
                volume=1000, amount=c * 100000, turnover_rate=0.0,
                pct_change=0.5, vwap=c,
            ))
        await s.commit()

    reset_metrics_archive_state()
    # trade_date 取 2026-12-31：func.date(ts) <= 该日 → 覆盖全部 60 根
    # （最后一根 = 2026-04-01 + 59d = 2026-05-30）
    result = await archive_daily_metrics(factory, date(2026, 12, 31))
    assert result["total"] == 1
    assert result["ok"] == 1 and result["failed"] == 0

    async with factory() as s:
        m = (await s.execute(
            select(StockMetric).where(StockMetric.secucode == "600519.SH")
        )).scalars().all()
        assert len(m) == 1
        assert m[0].score >= 3
        assert m[0].signal_level == "strong_bull"
        assert m[0].pct_change == 0.5  # 最后一根日K pct_change 透传

    await engine.dispose()
