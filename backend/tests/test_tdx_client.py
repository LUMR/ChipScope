from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from app.services.collector.tdx_client import TdxClient


def _fake_df():
    data = {
        "price": [10.5], "open": [10.2], "last_close": [10.3],
        "high": [10.6], "low": [10.1], "vol": [1000.0], "amount": [1050000.0],
    }
    for i in range(1, 6):
        data[f"bid{i}"] = [10.4 - i * 0.01]
        data[f"bid_vol{i}"] = [100.0 * i]
        data[f"ask{i}"] = [10.6 + i * 0.01]
        data[f"ask_vol{i}"] = [200.0 * i]
    return pd.DataFrame(data)


class _FakeMootdx:
    def quotes(self, symbol):
        return _fake_df()


@pytest.mark.asyncio
async def test_quotes_parses_five_levels():
    client = TdxClient(client=_FakeMootdx(), executor=ThreadPoolExecutor(max_workers=1))
    q = await client.quotes("600519")
    assert q.price == 10.5
    assert q.secucode == "600519"
    assert len(q.bids) == 5 and len(q.asks) == 5
    assert q.bids[0] == (10.39, 100.0)
    assert q.asks[0] == (10.61, 200.0)
    client.close()


class _FakeMootdxBars:
    """模拟 mootdx Quotes.client.bars 的返回（日K DataFrame）。vol 单位：手，amount 单位：元。"""
    def bars(self, symbol, frequency, offset):
        return pd.DataFrame([
            {"datetime": "2026-06-12 15:00", "open": 38.5, "close": 39.3,
             "high": 39.4, "low": 38.3, "vol": 1119833, "amount": 4.373132e9},
            {"datetime": "2026-06-13 15:00", "open": 39.2, "close": 38.9,
             "high": 39.4, "low": 38.7, "vol": 977404, "amount": 3.81179e9},
        ])


@pytest.mark.asyncio
async def test_daily_bars_maps_fields_and_turnover():
    tdx = TdxClient(client=_FakeMootdxBars())
    try:
        bars = await tdx.daily_bars("600036", count=2, float_shares=2.06e10)
    finally:
        tdx.close()
    assert len(bars) == 2
    b0 = bars[0]
    assert b0.date == "2026-06-12"
    assert b0.open == 38.5 and b0.close == 39.3 and b0.high == 39.4 and b0.low == 38.3
    assert b0.volume == 1119833
    # vwap = amount / (vol×100) = 4.373132e9 / 111983300 ≈ 39.05
    assert b0.vwap == pytest.approx(39.05, abs=0.05)
    # turnover = vol×100 / float_shares × 100 = 111983300 / 2.06e10 × 100 ≈ 0.544%
    assert b0.turnover_rate == pytest.approx(0.544, abs=0.01)
    # pct_change 首日为 0（无前日）
    assert b0.pct_change == 0.0
    # 次日 pct 由前日 close 推算：(38.9-39.3)/39.3×100 ≈ -1.018
    assert bars[1].pct_change == pytest.approx(-1.018, abs=0.01)


@pytest.mark.asyncio
async def test_daily_bars_no_float_shares_zero_turnover():
    tdx = TdxClient(client=_FakeMootdxBars())
    try:
        bars = await tdx.daily_bars("600036", count=2, float_shares=0)
    finally:
        tdx.close()
    assert all(b.turnover_rate == 0.0 for b in bars)


@pytest.mark.asyncio
async def test_daily_bars_zero_volume_no_div_zero():
    class FakeZero:
        def bars(self, symbol, frequency, offset):
            return pd.DataFrame([
                {"datetime": "2026-06-12 15:00", "open": 0, "close": 0, "high": 0,
                 "low": 0, "vol": 0, "amount": 0},
            ])
    tdx = TdxClient(client=FakeZero())
    try:
        bars = await tdx.daily_bars("600036", count=1, float_shares=1e10)
    finally:
        tdx.close()
    assert bars[0].vwap == 0.0
    assert bars[0].turnover_rate == 0.0
