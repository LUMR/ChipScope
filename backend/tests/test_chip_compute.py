import pytest
from sqlalchemy import select

from app.models.chip import ChipDistribution
from app.services.chip_compute import compute_chip_series, upsert_chip_distribution
from app.utils.time import trading_day_ts


def _klines():
    return [
        {"ts": trading_day_ts("2026-06-11"), "low": 10.0, "high": 12.0, "vwap": 11.0,
         "volume": 10000, "turnover_rate": 5.0, "close": 11.0},
        {"ts": trading_day_ts("2026-06-12"), "low": 11.0, "high": 13.0, "vwap": 12.0,
         "volume": 15000, "turnover_rate": 5.0, "close": 12.0},
        {"ts": trading_day_ts("2026-06-13"), "low": 12.0, "high": 14.0, "vwap": 13.0,
         "volume": 8000, "turnover_rate": 5.0, "close": 13.0},
    ]


def test_compute_chip_series_accumulates():
    centers, results = compute_chip_series(_klines(), decay_coeff=2.0)
    assert len(results) == 3
    assert all(r["dist"].sum() > 0 for r in results)
    # 平均成本落在 bin 区间内
    lo, hi = centers[0], centers[-1]
    for r in results:
        assert lo <= r["avg_cost"] <= hi
    # 获利盘比例合法
    for r in results:
        assert 0.0 <= r["profit_ratio"] <= 1.0


def test_compute_chip_series_first_day_only_today():
    """首日无旧筹码，分布即当日三角形。"""
    klines = [_klines()[0]]
    centers, results = compute_chip_series(klines, decay_coeff=2.0)
    # 首日 eff = 5*2/100 = 0.1，new = today*0.1 + 0*0.9 = today*0.1
    assert results[0]["dist"].sum() == pytest.approx(10000 * 0.1, rel=1e-4)


@pytest.mark.asyncio
async def test_upsert_chip_distribution(db_session):
    centers, results = compute_chip_series(_klines(), decay_coeff=2.0)
    n = await upsert_chip_distribution(db_session, "600519.SH", centers, results, 2.0)
    assert n == 3
    rows = (
        await db_session.execute(
            select(ChipDistribution).execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert len(rows) == 3
    assert rows[0].secucode == "600519.SH"
    assert isinstance(rows[0].distribution, dict)
    assert float(rows[0].decay_coeff) == 2.0
