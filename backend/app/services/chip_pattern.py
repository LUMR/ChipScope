"""筹码形态识别（设计文档第八节）。纯函数。"""


def recognize(concentration: float, peak_price: float, peak_ratio: float,
              current_price: float) -> dict:
    """识别筹码形态，返回最显著的形态。

    Args:
        concentration: 90% 集中度（0-1 量级，如 0.12）
        peak_price: 筹码峰价位
        peak_ratio: 峰值区（峰±2%）筹码占比（0-1）
        current_price: 现价

    规则：
        单峰密集: concentration < 0.15 且 peak_ratio > 0.40
        高位单峰: 单峰密集 + 现价 > 峰位×1.05
        低位单峰: 单峰密集 + 现价 < 峰位×0.95
        筹码发散: concentration > 0.30
    """
    is_dense = concentration < 0.15 and peak_ratio > 0.40
    if is_dense:
        if current_price > peak_price * 1.05:
            return _form("高位单峰", 0.8,
                         f"低位筹码获利了结风险：现价{current_price:.2f}高于峰位{peak_price:.2f}")
        if current_price < peak_price * 0.95:
            return _form("低位单峰", 0.8,
                         f"高位筹码割肉可能见底：现价{current_price:.2f}低于峰位{peak_price:.2f}")
        return _form("单峰密集", 0.85,
                     f"90%筹码集中度{concentration:.1%}，峰值区占比{peak_ratio:.0%}，关注突破方向")
    if concentration > 0.30:
        return _form("筹码发散", 0.7,
                     f"90%集中度{concentration:.1%}，上方套牢盘多，上涨阻力大")
    return _form("无明显形态", 0.0, "")


def recognize_trend(avg_cost_series: list[float]) -> dict:
    """筹码上下移：近 30 天平均成本单调性。"""
    recent = avg_cost_series[-30:]
    if len(recent) < 5:
        return _form("无明显形态", 0.0, "")
    down = all(recent[i] >= recent[i + 1] for i in range(len(recent) - 1))
    up = all(recent[i] <= recent[i + 1] for i in range(len(recent) - 1))
    if down:
        return _form("筹码下移", 0.75, "近30天平均成本持续下降，恐慌抛售")
    if up:
        return _form("筹码上移", 0.75, "近30天平均成本持续上升，资金吸筹")
    return _form("无明显形态", 0.0, "")


def _form(name: str, confidence: float, description: str) -> dict:
    return {"name": name, "confidence": confidence, "description": description}
