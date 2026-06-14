import numpy as np
import pytest

from app.services.chip_metrics import (
    avg_cost,
    concentration_90,
    peak_price,
    profit_ratio,
)


def test_profit_ratio():
    centers = np.array([10.0, 15.0, 20.0])
    dist = np.array([30.0, 50.0, 20.0])
    # 现价 15：price<=15 的筹码 = 30+50=80，总 100 → 0.8
    assert profit_ratio(centers, dist, current_price=15.0) == pytest.approx(0.8)


def test_profit_ratio_empty():
    assert profit_ratio(np.array([10.0]), np.array([0.0]), 10.0) == 0.0


def test_avg_cost():
    centers = np.array([10.0, 20.0])
    dist = np.array([50.0, 50.0])
    assert avg_cost(centers, dist) == pytest.approx(15.0)


def test_concentration_90_single_price():
    # 全集中在 15 一个价位 → 90% 区间宽度为 0
    centers = np.array([10.0, 15.0, 20.0])
    dist = np.array([0.0, 100.0, 0.0])
    low, high, conc = concentration_90(centers, dist)
    assert conc == pytest.approx(0.0, abs=0.05)


def test_concentration_90_spread():
    # 均匀分布 → 集中度较高
    centers = np.array([10.0, 15.0, 20.0])
    dist = np.array([33.0, 34.0, 33.0])
    _, _, conc = concentration_90(centers, dist)
    assert conc > 0.3


def test_peak_price():
    centers = np.array([10.0, 15.0, 20.0])
    dist = np.array([10.0, 80.0, 10.0])
    assert peak_price(centers, dist) == pytest.approx(15.0)
