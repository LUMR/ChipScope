import numpy as np
import pytest

from app.services.chip_engine import decay_step, price_bins, triangle_distribution


def test_price_bins_covers_range():
    centers, step = price_bins(low=10.0, high=20.0, num=400)
    assert len(centers) == 400
    assert centers[0] == pytest.approx(10.0)
    assert centers[-1] == pytest.approx(20.0)


def test_triangle_distribution_peak_at_vwap():
    centers, _ = price_bins(low=10.0, high=20.0, num=400)
    tri = triangle_distribution(centers, low=10.0, vwap=15.0, high=20.0, volume=10000.0)
    # 总量 = volume
    assert tri.sum() == pytest.approx(10000.0, rel=1e-4)
    # 峰在 vwap 附近
    assert centers[int(np.argmax(tri))] == pytest.approx(15.0, abs=0.1)
    # 两端趋近 0
    assert tri[0] == pytest.approx(0.0, abs=1e-6)
    assert tri[-1] == pytest.approx(0.0, abs=1e-6)


def test_decay_step_caps_effective_turnover():
    """P0-4: 有效换手率截断 0.95，防止旧筹码权重为负。"""
    old = np.ones(400) * 100.0
    today = np.ones(400) * 50.0
    # 换手率 30%，衰减系数 5 → 有效换手率 1.5 → 截断 0.95
    new = decay_step(old, today, turnover_rate=30.0, decay_coeff=5.0)
    # 旧权重 0.05：100*0.05=5；新权重 0.95：50*0.95=47.5
    assert new[0] == pytest.approx(52.5, rel=1e-4)


def test_decay_step_normal_case():
    old = np.ones(400) * 100.0
    today = np.ones(400) * 0.0
    # 换手率 5%，衰减 2 → 有效换手率 0.1
    new = decay_step(old, today, turnover_rate=5.0, decay_coeff=2.0)
    assert new[0] == pytest.approx(90.0, rel=1e-4)


def test_decay_step_preserves_total_when_full_turnover():
    """全换手（eff 截断 0.95）时旧筹码仍保留 5%，不会清零。"""
    old = np.ones(400) * 100.0
    today = np.ones(400) * 0.0
    new = decay_step(old, today, turnover_rate=100.0, decay_coeff=10.0)
    assert new.sum() == pytest.approx(100.0 * 400 * 0.05, rel=1e-4)
