"""筹码分布核心算法：价格分箱 + 三角形分布 + 衰减叠加。

纯 NumPy 向量化，无副作用，易测试。
"""
import numpy as np


def price_bins(low: float, high: float, num: int = 400):
    """返回 bin 中心数组 + 步长。覆盖 [low, high]，num 个等距 bin。"""
    centers = np.linspace(low, high, num)
    step = (high - low) / (num - 1) if num > 1 else 0.0
    return centers, step


def triangle_distribution(centers, low: float, vwap: float, high: float, volume: float):
    """以 vwap 为峰、[low, high] 为底的三角形分布，归一化总量 = volume。"""
    centers = np.asarray(centers, dtype=float)
    tri = np.zeros_like(centers)
    left = centers <= vwap
    right = ~left
    # 左半：从 low 线性上升到 vwap（峰）
    denom_l = (vwap - low) or 1e-9
    tri[left] = (centers[left] - low) / denom_l
    # 右半：从 vwap 线性下降到 high
    denom_r = (high - vwap) or 1e-9
    tri[right] = (high - centers[right]) / denom_r
    tri = np.clip(tri, 0.0, None)
    total = tri.sum()
    if total > 0:
        tri = tri / total * volume
    return tri


def decay_step(old_dist, today_tri, turnover_rate: float, decay_coeff: float):
    """衰减叠加（落实审查 P0-4：有效换手率截断 0.95）。

    effective_turnover = min(turnover_rate * decay_coeff / 100, 0.95)
    new = today_tri * eff + old_dist * (1 - eff)
    """
    eff = min(turnover_rate * decay_coeff / 100.0, 0.95)
    return today_tri * eff + np.asarray(old_dist) * (1.0 - eff)
