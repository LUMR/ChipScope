# backend/app/services/indicator.py
"""技术指标纯函数（NumPy，无 I/O）。仿 chip_engine 风格。

约定（见计划 Global Constraints）：
- EMA[t]=α·x[t]+(1-α)·EMA[t-1]，α=2/(n+1)，EMA[0]=x[0]
- 通达信 SMA[t]=(SMA[t-1]·(m-1)+x[t])/m，SMA[0]=x[0]
- sma 为简单移动平均（前 n-1 个为 nan）
- hhv/llv 为过去 n 根（含当根）最高/最低
"""
import numpy as np


def ema(x, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.empty_like(x)
    alpha = 2.0 / (n + 1)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


def sma(x, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full_like(x, np.nan)
    if n < 1 or len(x) < n:
        return out
    c = np.concatenate(([0.0], np.cumsum(x)))  # c[k] = sum(x[0..k-1])
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def sma_tdx(x, m: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = (out[i - 1] * (m - 1) + x[i]) / m
    return out


def hhv(x, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.empty(len(x))
    for i in range(len(x)):
        out[i] = np.max(x[max(0, i - n + 1):i + 1])
    return out


def llv(x, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.empty(len(x))
    for i in range(len(x)):
        out[i] = np.min(x[max(0, i - n + 1):i + 1])
    return out
