import pytest
from datetime import date
from sqlalchemy import select
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
