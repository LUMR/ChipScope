import pytest
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.base import Base
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.models.stock_metric import StockMetric
from app.services.ingest import upsert_stock_metric
from app.services.indicator import compute_indicators, score, signal_level
from app.services.collector.types import KlineBar
from app.services.metric_archive import (
    archive_daily_metrics,
    archive_metrics_range,
    reset_metrics_archive_state,
)


def _make_row(trade_date, secucode, **overrides):
    """构造一条 stock_metric 行，覆盖默认值。"""
    base = {
        "trade_date": trade_date, "secucode": secucode,
        "close": 1680.0, "open": 1670.0, "dif": 1.0, "dea": 0.5, "hist": 1.0,
        "k": 50.0, "d": 48.0, "j": 54.0, "wr": 60.0, "rsi": 55.0, "prev_rsi": 52.0,
        "ma5": 1670.0, "ma10": 1660.0, "ma20": 1650.0, "ma60": 1600.0,
        "ma20_prev5": 1620.0, "high20_prev": 1660.0, "high60_prev": 1640.0,
        "vol_ratio": 1.5, "pct5": 3.0, "consecutive_green": 2,
        "pct_change": 1.2,
        "score": 4, "signal_level": "strong_bull",
        "macd_signal": 1, "kdj_signal": 1, "wr_signal": 1, "rsi_signal": 1,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_upsert_stock_metric_inserts_and_updates(db_session):
    # stock_metric.secucode 有 FK → stock_meta，须先 seed 股票元数据
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()
    row = _make_row(date(2026, 6, 24), "600519.SH")
    n = await upsert_stock_metric(db_session, [row])
    assert n == 1

    got = (await db_session.execute(
        select(StockMetric).where(StockMetric.secucode == "600519.SH")
    )).scalars().one()
    assert got.score == 4 and got.signal_level == "strong_bull"
    assert got.close == 1680.0
    assert float(got.pct_change) == pytest.approx(1.2)  # Numeric 列读出 Decimal，勿与 float 直接 ==

    # 幂等 update：同 PK 再写，score 改变
    row["score"] = 0
    row["signal_level"] = "neutral"
    await upsert_stock_metric(db_session, [row])
    db_session.expire_all()  # Core upsert 绕过 ORM，identity map 里是陈旧实例
    got2 = (await db_session.execute(
        select(StockMetric).where(StockMetric.secucode == "600519.SH")
    )).scalars().one()
    assert got2.score == 0 and got2.signal_level == "neutral"


@pytest.mark.asyncio
async def test_upsert_stock_metric_multiple(db_session):
    """同时 upsert 多行。"""
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    db_session.add(StockMeta(secucode="000001.SZ", code="000001", name="平安银行",
                             market="SZ", secid="0.000001"))
    await db_session.commit()
    rows = [
        _make_row(date(2026, 6, 24), "600519.SH"),
        _make_row(date(2026, 6, 24), "000001.SZ", score=-3, signal_level="strong_bear"),
    ]
    n = await upsert_stock_metric(db_session, rows)
    assert n == 2
    got = (await db_session.execute(select(StockMetric))).scalars().all()
    assert len(got) == 2


@pytest.mark.asyncio
async def test_upsert_stock_metric_empty():
    """空列表短路。"""
    result = await upsert_stock_metric(None, [])
    assert result == 0


# ── archive 服务测试 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_archive_daily_metrics_computes_and_upserts(db_session):
    """seed 60 根日K → archive_daily_metrics → 物化值 = compute_indicators 实时算值。"""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, daily_kline, stock_metric CASCADE"))
    # seed：60 根持续上涨（用 timedelta 跨月避免日期越界）
    async with factory() as s:
        s.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                        market="SH", secid="1.600519"))
        await s.commit()  # meta 先落库（daily_kline 有 FK→stock_meta，混批 flush 会 FK violation）
        base_ts = datetime(2026, 4, 1, tzinfo=timezone.utc)
        for i in range(60):
            ts = base_ts + timedelta(days=i)
            s.add(DailyKline(ts=ts, secucode="600519.SH",
                             open=100.0 + i, close=100.0 + i, high=101.0 + i,
                             low=99.0, volume=1000, amount=1e7,
                             turnover_rate=0.5, pct_change=1.0, vwap=100.0 + i))
        await s.commit()

    reset_metrics_archive_state()
    # 单日路径只处理「当日实际有 bar」的股 → trade_date 取 seed 最后一天（4/1 + 59 天）
    trade_date = date(2026, 5, 30)
    result = await archive_daily_metrics(factory, trade_date)
    assert result["total"] == 1
    assert result["ok"] == 1 and result["failed"] == 0

    # 验证物化值 = 实时算值（用同一份 bars）
    async with factory() as s:
        m = (await s.execute(select(StockMetric).where(StockMetric.secucode == "600519.SH"))).scalars().all()
        assert len(m) == 1
        row = m[0]
        # 用同一批 seed 数据重算，比对关键字段
        async with factory() as s2:
            krows = (await s2.execute(
                select(DailyKline).where(DailyKline.secucode == "600519.SH")
                .order_by(DailyKline.ts.desc()).limit(60)
            )).scalars().all()
            krows = list(reversed(krows))
        bars = [KlineBar(str(r.ts.date()), float(r.open), float(r.close), float(r.high),
                         float(r.low), int(r.volume), float(r.amount), float(r.pct_change),
                         float(r.turnover_rate), float(r.vwap)) for r in krows]
        ind = compute_indicators(bars)
        assert abs(float(row.dif) - ind["dif"]) < 0.001
        assert abs(float(row.ma20) - ind["ma20"]) < 0.001
        assert row.score == score(ind)
        assert row.signal_level == signal_level(score(ind))
        assert row.pct_change == 1.0  # 透传 pct_change

    await engine.dispose()


@pytest.mark.asyncio
async def test_archive_daily_metrics_nan_ma60_null(db_session):
    """35 根（30–59 区间）→ ma60 NaN 落 NULL，其余指标正常物化。"""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, daily_kline, stock_metric CASCADE"))
    async with factory() as s:
        s.add(StockMeta(secucode="301999.SZ", code="301999", name="次新股",
                        market="SZ", secid="0.301999"))
        await s.commit()  # meta 先落库（同上）
        base_ts = datetime(2026, 4, 1, tzinfo=timezone.utc)
        for i in range(35):
            s.add(DailyKline(ts=base_ts + timedelta(days=i), secucode="301999.SZ",
                             open=100.0, close=100.0 + i, high=101.0,
                             low=99.0, volume=1000, amount=1e7,
                             turnover_rate=0.5, pct_change=1.0, vwap=100.0))
        await s.commit()

    trade_date = date(2026, 5, 5)  # 最后一根：4/1 + 34 天
    result = await archive_daily_metrics(factory, trade_date)
    assert result["ok"] == 1

    async with factory() as s:
        row = (await s.execute(
            select(StockMetric).where(StockMetric.secucode == "301999.SZ")
        )).scalars().one()
        assert row.ma60 is None       # NaN → NULL
        assert row.ma5 is not None    # 35 根足够 ma5/ma10/ma20
        assert row.score is not None  # score 不依赖 ma60
    await engine.dispose()


@pytest.mark.asyncio
async def test_archive_metrics_range(db_session):
    """回填多日：按股一次加载，窗口内每个实际交易日物化一行，窗口外不落。"""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, daily_kline, stock_metric CASCADE"))
    async with factory() as s:
        s.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                        market="SH", secid="1.600519"))
        await s.commit()  # meta 先落库（同上）
        # 45 根（3/1..4/14）：保证窗口首日 4/1 已有 32 根（≥30 门槛）
        base_ts = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for i in range(45):
            ts = base_ts + timedelta(days=i)
            s.add(DailyKline(ts=ts, secucode="600519.SH",
                             open=100.0, close=100.0 + i, high=101.0,
                             low=99.0, volume=1000, amount=1e7,
                             turnover_rate=0.5, pct_change=1.0, vwap=100.0))
        await s.commit()

    reset_metrics_archive_state()
    result = await archive_metrics_range(factory, date(2026, 4, 1), date(2026, 4, 10))
    assert result["days"] == 10      # 窗口内 10 个交易日
    assert result["total"] == 1      # 1 只股（按股计数）
    assert result["ok"] == 1 and result["failed"] == 0

    async with factory() as s:
        rows = (await s.execute(select(StockMetric))).scalars().all()
        assert {r.trade_date for r in rows} == {
            date(2026, 4, 1) + timedelta(days=i) for i in range(10)
        }  # 每个交易日一行；窗口外（3 月、4/11–14）不物化
    await engine.dispose()
