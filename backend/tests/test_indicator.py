# backend/tests/test_indicator.py
import numpy as np
from numpy.testing import assert_array_almost_equal
from app.services.indicator import ema, sma, sma_tdx, hhv, llv


def test_ema_seed_and_recurrence():
    # EMA[0]=x[0]; α=2/3 → EMA[1]=2/3·1 + 1/3·10 = 4.0
    out = ema([10.0, 1.0], 2)
    assert_array_almost_equal(out, [10.0, 4.0])


def test_sma_simple_window():
    out = sma([1.0, 2.0, 3.0, 4.0], 2)
    assert np.isnan(out[0])
    assert_array_almost_equal(out[1:], [1.5, 2.5, 3.5])


def test_sma_n1_is_identity():
    assert_array_almost_equal(sma([1.0, 2.0, 3.0], 1), [1.0, 2.0, 3.0])


def test_sma_tdx_recurrence():
    # SMA[0]=x[0]; M=3 → SMA[1]=(10·2+1)/3=7
    out = sma_tdx([10.0, 1.0], 3)
    assert_array_almost_equal(out, [10.0, 7.0])


def test_hhv_llv_window_inclusive():
    h = hhv([1.0, 5.0, 3.0, 2.0], 2)   # 含当根的过去2根最大
    l = llv([1.0, 5.0, 3.0, 2.0], 2)
    assert_array_almost_equal(h[2:], [5.0, 3.0])  # i=2:max(5,3)=5; i=3:max(3,2)=3
    assert_array_almost_equal(l[2:], [3.0, 2.0])


from app.services.collector.types import KlineBar
from app.services.indicator import (
    compute_indicators,
    macd_signal,
    kdj_signal,
    wr_signal,
    rsi_signal,
    score,
    signal_level,
)


def _bar(c, o=None, h=None, low=None, vol=1000):
    o = o if o is not None else c
    h = h if h is not None else c * 1.01
    low = low if low is not None else c * 0.99
    return KlineBar("2026-01-01", o, c, h, low, vol, c * vol * 100, 0.0, 0.0, c)


def test_compute_indicators_fields_and_dif_sign():
    # 持续上涨 60 根 → DIF>0（短期 EMA > 长期 EMA）
    bars = [_bar(100 + i) for i in range(60)]
    ind = compute_indicators(bars)
    assert set(ind) >= {"dif", "dea", "hist", "k", "d", "j", "wr", "rsi",
                        "prev_rsi", "ma5", "ma20", "vol_ratio", "close",
                        "high20_prev", "high60_prev", "pct5", "consecutive_green"}
    assert ind["dif"] > 0


def test_compute_indicators_kdj_j_below_20_on_crash():
    # 持续下跌 → RSV≈0 → K/D/J 极低，J<20
    bars = [_bar(200 - i) for i in range(60)]
    ind = compute_indicators(bars)
    assert ind["j"] < 20


def test_compute_indicators_wr_near_100_on_crash():
    bars = [_bar(200 - i) for i in range(60)]
    ind = compute_indicators(bars)
    # 收盘接近区间最低 → WR 接近 100（超卖）
    assert ind["wr"] > 80


def test_compute_indicators_breakout_high20_prev():
    # 前 20 根高点 120，今日 130 突破
    bars = [_bar(100) for _ in range(20)] + [_bar(120) for _ in range(20)] + [_bar(130)]
    ind = compute_indicators(bars)
    assert ind["close"] > ind["high20_prev"]


def test_macd_signal_bull_and_bear():
    assert macd_signal({"dif": 1.0, "dea": 0.5}) == 1     # dif>dea 且 dif>0
    assert macd_signal({"dif": -1.0, "dea": -0.5}) == -1  # dif<dea 且 dif<0
    assert macd_signal({"dif": 1.0, "dea": 2.0}) == 0     # dif>0 但 dif<dea


def test_kdj_signal_low_golden_cross_and_overbought():
    assert kdj_signal({"k": 30, "d": 20, "j": 40}) == 1   # k>d 且 j<50
    assert kdj_signal({"k": 20, "d": 30, "j": 85}) == -1  # k<d 且 j>80
    assert kdj_signal({"k": 60, "d": 50, "j": 70}) == 0


def test_wr_signal_oversold_overbought():
    assert wr_signal({"wr": 85}) == 1
    assert wr_signal({"wr": 15}) == -1
    assert wr_signal({"wr": 50}) == 0


def test_rsi_signal_oversold_and_cross_up():
    assert rsi_signal({"rsi": 25, "prev_rsi": 25}) == 1   # 超卖
    assert rsi_signal({"rsi": 52, "prev_rsi": 49}) == 1   # 上穿 50
    assert rsi_signal({"rsi": 75, "prev_rsi": 75}) == -1  # 超买
    assert rsi_signal({"rsi": 55, "prev_rsi": 55}) == 0


def test_score_and_levels():
    ind = {"dif": 1, "dea": 0.5, "k": 30, "d": 20, "j": 40,
           "wr": 85, "rsi": 25, "prev_rsi": 25}
    assert score(ind) == 4
    assert signal_level(4) == "strong_bull"
    assert signal_level(2) == "bull"
    assert signal_level(0) == "neutral"
    assert signal_level(-2) == "bear"
    assert signal_level(-3) == "strong_bear"
