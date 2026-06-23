import pytest

from app.services.collector.tdx_client import _row_to_time
from app.services.market_minute import limit_pct, classify, aggregate, ranking_at, stock_series


def test_limit_pct_main_vs_gem():
    assert limit_pct("600519") == 10.0
    assert limit_pct("000001") == 10.0
    assert limit_pct("300750") == 20.0
    assert limit_pct("301236") == 20.0
    assert limit_pct("688981") == 20.0


def test_classify_five_buckets():
    assert classify(9.9, 10.0) == "limit_up"      # >= 10-0.3
    assert classify(10.0, 10.0) == "limit_up"
    assert classify(19.8, 20.0) == "limit_up"
    assert classify(-9.9, 10.0) == "limit_down"
    assert classify(5.0, 10.0) == "up"
    assert classify(-5.0, 10.0) == "down"
    assert classify(0.005, 10.0) == "flat"
    assert classify(-0.005, 10.0) == "flat"


def _row(secucode, pre_close, prices):
    """构造一行：prices[i] 是第 i 个时刻的价；时刻 0=09:31。"""
    return {
        "secucode": secucode,
        "pre_close": pre_close,
        "name": secucode,
        "points": [{"t": _row_to_time(i), "price": p, "vol": 100} for i, p in enumerate(prices)],
    }


def test_aggregate_avg_and_buckets_and_skip_zero_pre_close():
    from app.services.collector.tdx_client import _row_to_time as idx2t
    # A 主板 pre_close=100，全程 +5%（up）；B 创业板 pre_close=100，第 0 时刻 +20%（涨停）；
    # C pre_close=0（应被剔除）；D 主板 pre_close=100，-6%（down）
    rows = [
        _row("600519.SH", 100.0, [105.0, 105.0, 105.0, 105.0]),
        _row("300750.SZ", 100.0, [120.0, 105.0, 105.0, 105.0]),
        _row("000001.SZ", 0.0, [105.0, 105.0, 105.0, 105.0]),     # 剔除
        _row("601318.SH", 100.0, [94.0, 94.0, 94.0, 94.0]),
    ]
    out = aggregate(rows)
    assert out["summary"]["with_pre_close"] == 3
    assert out["summary"]["total"] == 4
    # 时刻 0：A+5 / B+20涨停 / D-6 → avg=(5+20-6)/3≈6.33
    p0 = out["series"][0]
    assert round(p0["avg_pct"], 2) == 6.33
    assert p0["limit_up"] == 1   # B
    assert p0["up"] == 1         # A
    assert p0["down"] == 1       # D
    assert p0["flat"] == 0
    assert p0["limit_down"] == 0
    # 时刻 1：A+5 / B+5 / D-6 → 涨停 0
    p1 = out["series"][1]
    assert p1["limit_up"] == 0
    assert p1["up"] == 2 and p1["down"] == 1


def test_aggregate_empty_rows():
    out = aggregate([])
    assert out["series"] == []
    assert out["summary"]["total"] == 0 and out["summary"]["with_pre_close"] == 0


def test_ranking_at_top_n_gainers_losers():
    rows = [
        _row("600519.SH", 100.0, [110.0]),   # +10 涨停
        _row("000001.SZ", 100.0, [105.0]),   # +5
        _row("300750.SZ", 100.0, [94.0]),    # -6
        _row("601318.SH", 100.0, [90.0]),    # -10 跌停
    ]
    out = ranking_at(rows, time_index=0, n=2)
    assert out["time"] == "09:31"
    assert [g["secucode"] for g in out["gainers"]] == ["600519.SH", "000001.SZ"]
    assert [l["secucode"] for l in out["losers"]] == ["601318.SH", "300750.SZ"]
    assert out["gainers"][0]["pct"] == 10.0


def test_ranking_at_skips_missing_pre_close():
    rows = [_row("600519.SH", 0.0, [110.0]), _row("000001.SZ", 100.0, [105.0])]
    out = ranking_at(rows, time_index=0)
    assert len(out["gainers"]) == 1 and out["gainers"][0]["secucode"] == "000001.SZ"


def test_stock_series_with_and_without_pre_close():
    pts = [{"t": "09:31", "price": 105.0, "vol": 100}, {"t": "09:32", "price": 110.0, "vol": 200}]
    s1 = stock_series(pts, 100.0)
    assert s1 == [{"t": "09:31", "price": 105.0, "vol": 100, "pct": 5.0},
                  {"t": "09:32", "price": 110.0, "vol": 200, "pct": 10.0}]
    s2 = stock_series(pts, None)
    assert s2[0]["pct"] is None


@pytest.mark.asyncio
async def test_get_overview_reads_db_and_caches(db_session):
    from datetime import date
    from app.models.minute_quote import MinuteQuote
    from app.models.stock import StockMeta
    from app.services import market_minute as mm

    mm.reset_caches()
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    db_session.add(StockMeta(secucode="000001.SZ", code="000001", name="平安银行",
                             market="SZ", secid="0.000001"))
    await db_session.commit()
    db_session.add(MinuteQuote(trade_date=date(2026, 6, 22), secucode="600519.SH",
                               data=[{"t": "09:31", "price": 105.0, "vol": 100}], pre_close=100))
    db_session.add(MinuteQuote(trade_date=date(2026, 6, 22), secucode="000001.SZ",
                               data=[{"t": "09:31", "price": 94.0, "vol": 100}], pre_close=100))
    await db_session.commit()

    out = await mm.get_overview(db_session, date(2026, 6, 22))
    assert out["summary"]["with_pre_close"] == 2
    assert out["series"][0]["up"] == 1 and out["series"][0]["down"] == 1
    # 命中缓存：date(2026,6,22) in _overview_cache
    assert date(2026, 6, 22) in mm._overview_cache


@pytest.mark.asyncio
async def test_get_ranking_and_stock_and_dates(db_session):
    from datetime import date
    from app.models.minute_quote import MinuteQuote
    from app.models.stock import StockMeta
    from app.services import market_minute as mm

    mm.reset_caches()
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()
    db_session.add(MinuteQuote(trade_date=date(2026, 6, 18), secucode="600519.SH",
                               data=[{"t": "09:31", "price": 110.0, "vol": 5}], pre_close=100))
    await db_session.commit()

    rk = await mm.get_ranking(db_session, date(2026, 6, 18), "09:31")
    assert rk["gainers"][0]["secucode"] == "600519.SH"

    st = await mm.get_stock(db_session, date(2026, 6, 18), "600519.SH")
    assert st["points"][0]["pct"] == 10.0 and st["pre_close"] == 100.0
    assert await mm.get_stock(db_session, date(2026, 6, 18), "999999.SZ") is None

    dates = await mm.list_dates(db_session)
    assert dates == ["2026-06-18"]
