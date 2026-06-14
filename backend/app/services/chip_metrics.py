"""筹码衍生指标：获利盘、平均成本、90%集中度、筹码峰。纯函数。"""
import numpy as np


def profit_ratio(centers, dist, current_price: float) -> float:
    """获利盘比例：现价以下筹码量 / 总筹码量。"""
    centers = np.asarray(centers)
    dist = np.asarray(dist, dtype=float)
    total = dist.sum()
    if total == 0:
        return 0.0
    in_profit = dist[centers <= current_price].sum()
    return float(in_profit / total)


def avg_cost(centers, dist) -> float:
    """平均成本 = Σ(价格×筹码) / Σ(筹码)。"""
    centers = np.asarray(centers)
    dist = np.asarray(dist, dtype=float)
    total = dist.sum()
    if total == 0:
        return 0.0
    return float((centers * dist).sum() / total)


def concentration_90(centers, dist):
    """90% 集中度：从两端各去掉 5% 筹码后的价格边界。

    返回 (cost_low_90, cost_high_90, concentration)，
    concentration = (high-low)/(high+low)*2。
    """
    centers = np.asarray(centers)
    dist = np.asarray(dist, dtype=float)
    total = dist.sum()
    if total == 0:
        return 0.0, 0.0, 0.0
    cum = np.cumsum(dist)
    low_idx = int(np.searchsorted(cum, total * 0.05))
    high_idx = int(np.searchsorted(cum, total * 0.95))
    low_idx = min(low_idx, len(centers) - 1)
    high_idx = min(high_idx, len(centers) - 1)
    cl = float(centers[low_idx])
    ch = float(centers[high_idx])
    conc = (ch - cl) / (ch + cl) * 2 if (ch + cl) > 0 else 0.0
    return cl, ch, float(conc)


def peak_price(centers, dist) -> float:
    """筹码峰：筹码量最大的价格区间。"""
    centers = np.asarray(centers)
    dist = np.asarray(dist, dtype=float)
    if dist.sum() == 0:
        return 0.0
    return float(centers[int(np.argmax(dist))])
