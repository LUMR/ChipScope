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


def _rsi(closes: np.ndarray, n: int) -> np.ndarray:
    deltas = np.diff(closes, prepend=closes[0])
    up = np.where(deltas > 0, deltas, 0.0)
    down = np.where(deltas < 0, -deltas, 0.0)
    avg_up = sma_tdx(up, n)
    avg_down = sma_tdx(down, n)
    rs = avg_up / np.where(avg_down == 0, np.nan, avg_down)
    rsi = 100 - 100 / (1 + rs)
    return np.nan_to_num(rsi, nan=50.0, posinf=100.0, neginf=0.0)


def _calc_arrays(bars) -> dict:
    closes = np.array([b.close for b in bars], dtype=float)
    highs = np.array([b.high for b in bars], dtype=float)
    lows = np.array([b.low for b in bars], dtype=float)
    opens = np.array([b.open for b in bars], dtype=float)
    vols = np.array([b.volume for b in bars], dtype=float)
    dif = ema(closes, 12) - ema(closes, 26)
    dea = ema(dif, 9)
    hist = (dif - dea) * 2
    rsv = (closes - llv(lows, 9)) / (hhv(highs, 9) - llv(lows, 9)) * 100
    rsv = np.nan_to_num(rsv, nan=50.0)
    k = sma_tdx(rsv, 3)
    d = sma_tdx(k, 3)
    j = 3 * k - 2 * d
    wr = (hhv(highs, 14) - closes) / (hhv(highs, 14) - llv(lows, 14)) * 100
    wr = np.nan_to_num(wr, nan=50.0)
    return {
        "closes": closes, "highs": highs, "lows": lows, "opens": opens, "vols": vols,
        "dif": dif, "dea": dea, "hist": hist, "k": k, "d": d, "j": j, "wr": wr,
        "rsi": _rsi(closes, 6),
        "ma5": sma(closes, 5), "ma10": sma(closes, 10),
        "ma20": sma(closes, 20), "ma60": sma(closes, 60),
        "vol_ma5": sma(vols, 5),
    }


def _consecutive_green(opens: np.ndarray, closes: np.ndarray, i: int) -> int:
    cnt, j = 0, i
    while j >= 0 and closes[j] > opens[j]:
        cnt += 1
        j -= 1
    return cnt


def compute_indicators(bars) -> dict:
    """最新点指标快照（筛选用）。bars 升序、含当日，建议 >= 60 根。"""
    a = _calc_arrays(bars)
    i = len(a["closes"]) - 1
    closes, highs = a["closes"], a["highs"]

    def _last(arr, k=0):
        idx = i - k
        return float(arr[idx]) if idx >= 0 else float(arr[0])

    return {
        "close": float(closes[i]), "open": float(a["opens"][i]),
        "dif": float(a["dif"][i]), "dea": float(a["dea"][i]), "hist": float(a["hist"][i]),
        "k": float(a["k"][i]), "d": float(a["d"][i]), "j": float(a["j"][i]),
        "wr": float(a["wr"][i]), "rsi": float(a["rsi"][i]),
        "prev_rsi": _last(a["rsi"], 1),
        "ma5": float(a["ma5"][i]), "ma10": float(a["ma10"][i]),
        "ma20": float(a["ma20"][i]), "ma60": float(a["ma60"][i]),
        "ma20_prev5": _last(a["ma20"], 5),
        "high20_prev": float(np.max(highs[max(0, i - 20):i])) if i >= 1 else float(highs[i]),
        "high60_prev": float(np.max(highs[max(0, i - 60):i])) if i >= 1 else float(highs[i]),
        "vol_ratio": float(a["vols"][i] / a["vol_ma5"][i]) if a["vol_ma5"][i] > 0 else 0.0,
        "pct5": float((closes[i] / closes[i - 5] - 1) * 100) if i >= 5 else 0.0,
        "consecutive_green": _consecutive_green(a["opens"], closes, i),
    }
