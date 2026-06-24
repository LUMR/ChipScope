# 盘后技术选股筛选器 Implementation Plan（阶段 1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全市场盘后选股筛选器——基于 MACD/KDJ/WR/RSI 四大经典指标共振表决出多空信号，叠加均线/突破/放量辅助条件，筛出潜力股；并在 StockDetail 加四大指标副图供人工复核。

**Architecture:** 全市场日K回灌入库 → `indicator.py` 纯函数算指标 + 共振信号 → `POST /api/screener` 实时筛 → `ScreenerPage` 结果表 → 点行进 StockDetail 看四大指标副图。指标纯函数零 I/O（仿 `chip_engine`），筛选时每只取近 60 根日K实时算。

**Tech Stack:** FastAPI + SQLAlchemy async + PostgreSQL + NumPy（后端）；React 19 + TypeScript + Vite + ECharts + AntD（前端）。

**Spec:** `docs/superpowers/specs/2026-06-24-stock-screener-design.md`

## Global Constraints

- Python 3.12，全 async；sync 库（mootdx）必须 `run_in_executor`。
- 指标函数（`indicator.py`）是**纯 NumPy**：无 I/O、无副作用、不访问 DB，仿 `chip_engine` 风格。
- DB upsert 一律 PostgreSQL `ON CONFLICT DO UPDATE`（见 `ingest.py`）。
- 前端 API 走 `api/client.ts` 的 `apiGet<T>` / `apiPost<T>`。
- `secucode` = `{code}.{market}`（如 `600519.SH`）；`secid` = `{market_int}.{code}`。
- 测试用**真 PostgreSQL**（`conftest.py` 每 test TRUNCATE）；TCP/HTTP 用 fake，DB 不 mock。
- Git commit **无** Co-authored-by / Claude 签名（项目约定）。
- 指标定义（写死，不可变）：`EMA[t]=α·x[t]+(1-α)·EMA[t-1]`，`α=2/(N+1)`，`EMA[0]=x[0]`；通达信 `SMA[t]=(SMA[t-1]·(M-1)+x[t])/M`，`SMA[0]=x[0]`；KDJ 初始 `K=D=50`；WR 大=超卖=看多；HHV/LLV 为过去 N 根（含当根）最高/最低。

---

## File Structure

**后端（新建）**
- `backend/app/services/indicator.py` — 纯函数：辅助(ema/sma/sma_tdx/hhv/llv)、四大指标、`compute_indicators` 快照、`indicator_series` 时序、信号、共振、`evaluate_extras` 谓词。
- `backend/app/services/kline_archive.py` — 全市场日K回灌（仿 `minute_archive.py`）。
- `backend/app/api/screener.py` — `POST /api/screener` router。
- `backend/app/schemas/screener.py` — 请求/响应 Pydantic。
- `backend/tests/test_indicator.py` / `test_kline_archive.py` / `test_api_screener.py`

**后端（修改）**
- `backend/app/api/archive.py` — 加 `POST /api/archive/daily` + status（仿 minute）。
- `backend/app/api/stocks.py` — 加 `GET /api/stocks/{code}/indicators`（副图时序）。
- `backend/app/scheduler.py` — 加 `daily_kline_archive` cron（16:10）。
- `backend/app/main.py` — `include_router(screener_router)`。

**前端（新建）**
- `frontend/src/api/screener.ts` — `screenStocks(req)`。
- `frontend/src/pages/ScreenerPage.tsx` — 条件面板 + 结果表。
- `frontend/src/components/IndicatorCharts.tsx` — MACD/KDJ/WR/RSI 四副图。

**前端（修改）**
- `frontend/src/api/archive.ts` — 加 `triggerDailyKlineArchive` / `getDailyKlineArchiveStatus`。
- `frontend/src/pages/ArchivePage.tsx` — 加"日K回档"Card。
- `frontend/src/pages/StockDetail.tsx` — `<KLineChart>` 下插入 `<IndicatorCharts>`。
- `frontend/src/App.tsx` — 加 `/screener` 路由；`AppLayout` 导航加"选股"。

---

## Task 1: indicator 辅助函数（EMA/SMA/SMA_TDX/HHV/LLV）

**Files:**
- Create: `backend/app/services/indicator.py`
- Test: `backend/tests/test_indicator.py`

**Interfaces:**
- Produces: `ema(x, n) -> np.ndarray`、`sma(x, n) -> np.ndarray`、`sma_tdx(x, m) -> np.ndarray`、`hhv(x, n) -> np.ndarray`、`llv(x, n) -> np.ndarray`。后续指标任务依赖这些。

- [ ] **Step 1: 写失败测试**

```python
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
    # 前 n-1 个 nan；sma[2]=(2+3)/2=2.5; sma[3]=(3+4)/2=3.5
    assert np.isnan(out[0]) and np.isnan(out[1])
    assert_array_almost_equal(out[2:], [2.5, 3.5])


def test_sma_tdx_recurrence():
    # SMA[0]=x[0]; M=3 → SMA[1]=(10·2+1)/3=7
    out = sma_tdx([10.0, 1.0], 3)
    assert_array_almost_equal(out, [10.0, 7.0])


def test_hhv_llv_window_inclusive():
    h = hhv([1.0, 5.0, 3.0, 2.0], 2)   # 含当根的过去2根最大
    l = llv([1.0, 5.0, 3.0, 2.0], 2)
    assert_array_almost_equal(h[2:], [5.0, 3.0])  # i=2:max(5,3)=5; i=3:max(3,2)=3
    assert_array_almost_equal(l[2:], [3.0, 2.0])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_indicator.py -v`
Expected: FAIL（`ModuleNotFoundError: app.services.indicator`）

- [ ] **Step 3: 写最小实现**

```python
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
    c = np.cumsum(x)
    out[n - 1:] = (c[n - 1:] - np.concatenate(([0.0], c[:-n]))) / n
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_indicator.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/indicator.py backend/tests/test_indicator.py
git commit -m "feat(indicator): EMA/SMA/SMA_TDX/HHV/LLV 辅助函数"
```

---

## Task 2: 四大指标 + compute_indicators 快照

**Files:**
- Modify: `backend/app/services/indicator.py`
- Test: `backend/tests/test_indicator.py`

**Interfaces:**
- Consumes: Task 1 的辅助函数。
- Produces: `compute_indicators(bars: list[KlineBar]) -> dict`（最新点快照，字段见下）。`bars` 为 `app.services.collector.types.KlineBar` 列表（升序，含当日）。返回字段：`close, open, dif, dea, hist, k, d, j, wr, rsi, prev_rsi, ma5, ma10, ma20, ma60, ma20_prev5, high20_prev, high60_prev, vol_ratio, pct5, consecutive_green`。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_indicator.py
from app.services.collector.types import KlineBar
from app.services.indicator import compute_indicators


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_indicator.py -k compute -v`
Expected: FAIL（`ImportError: cannot import name 'compute_indicators'`）

- [ ] **Step 3: 写实现（追加到 indicator.py）**

```python
# 追加到 backend/app/services/indicator.py
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_indicator.py -k compute -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/indicator.py backend/tests/test_indicator.py
git commit -m "feat(indicator): MACD/KDJ/WR/RSI 计算 + compute_indicators 快照"
```

---

## Task 3: 四指标多空信号 + 共振综合

**Files:**
- Modify: `backend/app/services/indicator.py`
- Test: `backend/tests/test_indicator.py`

**Interfaces:**
- Consumes: `compute_indicators` 返回的 dict。
- Produces: `macd_signal(ind)`、`kdj_signal(ind)`、`wr_signal(ind)`、`rsi_signal(ind)` 各返回 `+1/0/-1`；`score(ind) -> int`；`signal_level(score) -> str`（`strong_bull/bull/neutral/bear/strong_bear`）。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_indicator.py
from app.services.indicator import (
    macd_signal, kdj_signal, wr_signal, rsi_signal, score, signal_level,
)


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_indicator.py -k "signal or score" -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 写实现（追加到 indicator.py）**

```python
# 追加到 backend/app/services/indicator.py
def macd_signal(ind: dict) -> int:
    if ind["dif"] > ind["dea"] and ind["dif"] > 0:
        return 1
    if ind["dif"] < ind["dea"] and ind["dif"] < 0:
        return -1
    return 0


def kdj_signal(ind: dict) -> int:
    if (ind["k"] > ind["d"] and ind["j"] < 50) or ind["j"] < 20:
        return 1
    if ind["k"] < ind["d"] and ind["j"] > 80:
        return -1
    return 0


def wr_signal(ind: dict) -> int:
    if ind["wr"] > 80:
        return 1
    if ind["wr"] < 20:
        return -1
    return 0


def rsi_signal(ind: dict) -> int:
    if ind["rsi"] < 30 or (ind["rsi"] >= 50 and ind["prev_rsi"] < 50):
        return 1
    if ind["rsi"] > 70:
        return -1
    return 0


def score(ind: dict) -> int:
    return macd_signal(ind) + kdj_signal(ind) + wr_signal(ind) + rsi_signal(ind)


def signal_level(s: int) -> str:
    if s >= 3:
        return "strong_bull"
    if s >= 1:
        return "bull"
    if s == 0:
        return "neutral"
    if s >= -2:
        return "bear"
    return "strong_bear"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_indicator.py -k "signal or score" -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/indicator.py backend/tests/test_indicator.py
git commit -m "feat(indicator): 四指标多空信号 + 共振综合 score/signal_level"
```

---

## Task 4: 辅助条件谓词 evaluate_extras

**Files:**
- Modify: `backend/app/services/indicator.py`
- Test: `backend/tests/test_indicator.py`

**Interfaces:**
- Consumes: `compute_indicators` dict + extras 列表（`[{"type": "ma_bull"}, {"type":"breakout","n":20}, ...]`）。
- Produces: `evaluate_extras(ind: dict, extras: list[dict]) -> bool`（全满足返回 True）。支持 type：`ma_bull, above_ma(n), ma_up, breakout(n=20/60), new_high, volume_up(k), volume_up_green(k), pct_range(lo,hi), consecutive_green(k)`。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_indicator.py
from app.services.indicator import evaluate_extras


def _bull_ind():
    return {"close": 130, "open": 125, "ma5": 128, "ma10": 126, "ma20": 124,
            "ma60": 120, "ma20_prev5": 110, "high20_prev": 120, "high60_prev": 122,
            "vol_ratio": 2.5, "pct5": 8.0, "consecutive_green": 4}


def test_evaluate_extras_all_pass():
    ind = _bull_ind()
    assert evaluate_extras(ind, [{"type": "ma_bull"}, {"type": "breakout", "n": 20},
                                 {"type": "volume_up"}]) is True


def test_evaluate_extras_breakout_60():
    ind = _bull_ind()
    assert evaluate_extras(ind, [{"type": "breakout", "n": 60}]) is True  # 130>122


def test_evaluate_extras_volume_up_green_pass_and_fail():
    ind = _bull_ind()
    assert evaluate_extras(ind, [{"type": "volume_up_green"}]) is True  # vol_ratio>2 且 close>open
    ind2 = {**ind, "close": 120, "open": 125}  # 收阴
    assert evaluate_extras(ind2, [{"type": "volume_up_green"}]) is False


def test_evaluate_extras_empty_list_passes():
    assert evaluate_extras(_bull_ind(), []) is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_indicator.py -k evaluate -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 写实现（追加到 indicator.py）**

```python
# 追加到 backend/app/services/indicator.py
def evaluate_extras(ind: dict, extras: list[dict]) -> bool:
    """辅助条件 AND 组合，全满足返回 True。"""
    for e in extras or []:
        t = e.get("type")
        if t == "ma_bull":
            if not (ind["ma5"] > ind["ma10"] > ind["ma20"] > ind["ma60"]):
                return False
        elif t == "above_ma":
            n = e.get("n", 20)
            if not (ind["close"] > ind[f"ma{n}"]):
                return False
        elif t == "ma_up":
            if not (ind["ma20"] > ind["ma20_prev5"]):
                return False
        elif t == "breakout":
            ref = ind["high20_prev"] if e.get("n", 20) == 20 else ind["high60_prev"]
            if not (ind["close"] > ref):
                return False
        elif t == "new_high":
            if not (ind["close"] >= ind["high60_prev"] * 0.98):
                return False
        elif t == "volume_up":
            if not (ind["vol_ratio"] > e.get("k", 2.0)):
                return False
        elif t == "volume_up_green":
            if not (ind["vol_ratio"] > e.get("k", 2.0) and ind["close"] > ind["open"]):
                return False
        elif t == "pct_range":
            if not (e.get("lo", 3) <= ind["pct5"] <= e.get("hi", 15)):
                return False
        elif t == "consecutive_green":
            if not (ind["consecutive_green"] >= e.get("k", 3)):
                return False
    return True
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_indicator.py -k evaluate -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/indicator.py backend/tests/test_indicator.py
git commit -m "feat(indicator): 辅助条件谓词 evaluate_extras"
```

---

## Task 5: 全市场日K回灌 kline_archive

**Files:**
- Create: `backend/app/services/kline_archive.py`
- Test: `backend/tests/test_kline_archive.py`

**Interfaces:**
- Consumes: `TdxClient.daily_bars(symbol, count)`（升序 KlineBar 列表）、`ingest.upsert_daily_kline(session, secucode, bars)`、`minute_archive._filter_a_shares` / `refresh_stock_universe`（复用全市场清单）。
- Produces: `archive_daily_klines(session_factory, tdx, trade_date, count=250, on_progress=None) -> dict`（`{trade_date,total,ok,failed}`）；进程内状态 `get_daily_kline_archive_status / is_daily_kline_archive_running / set_*` + `reset_daily_kline_archive_state()`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_kline_archive.py
import pandas as pd
import pytest
from datetime import date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.config import get_settings
from app.models.base import Base
from app.models.kline import DailyKline
from app.services.kline_archive import (
    archive_daily_klines, reset_daily_kline_archive_state,
)


class _FakeTdx:
    async def stocks(self, market: int):
        if market == 1:
            return pd.DataFrame({"code": ["600519"], "name": ["贵州茅台"],
                                 "volunit": [100], "decimal_point": [2], "pre_close": [100.0]})
        return pd.DataFrame({"code": ["000001"], "name": ["平安银行"],
                             "volunit": [100], "decimal_point": [2], "pre_close": [10.0]})

    async def daily_bars(self, symbol: str, count: int = 250, float_shares: float = 0.0):
        from app.services.collector.types import KlineBar
        # 返回两根，第二根日期为 trade_date
        return [KlineBar("2026-06-23", 99, 100, 101, 98, 1000, 1e7, 1.0, 0.1, 100),
                KlineBar("2026-06-24", 100, 105, 106, 99, 2000, 2e7, 5.0, 0.2, 105)]


@pytest.mark.asyncio
async def test_archive_daily_klines_upserts(db_session):
    _engine = create_async_engine(get_settings().database_url)
    _factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, daily_kline CASCADE"))

    reset_daily_kline_archive_state()
    result = await archive_daily_klines(_factory, _FakeTdx(), date(2026, 6, 24), count=10)
    assert result == {"trade_date": "2026-06-24", "total": 2, "ok": 2, "failed": 0}

    rows = (await db_session.execute(
        select(DailyKline.secucode).order_by(DailyKline.secucode)
    )).scalars().all()
    assert rows == ["000001.SZ", "600519.SH"]
    await _engine.dispose()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_kline_archive.py -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 写实现**

```python
# backend/app/services/kline_archive.py
"""全市场日K回档：复用 minute_archive 的清单刷新 + 进度状态模式。"""
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.services.collector.tdx_client import TdxClient
from app.services.ingest import upsert_daily_kline
from app.services.minute_archive import refresh_stock_universe

_running = False
_status: dict | None = None


def get_daily_kline_archive_status() -> dict | None:
    return _status


def is_daily_kline_archive_running() -> bool:
    return _running


def set_daily_kline_archive_running(value: bool) -> None:
    global _running
    _running = value


def set_daily_kline_archive_status(value: dict | None) -> None:
    global _status
    _status = value


def reset_daily_kline_archive_state() -> None:
    global _running, _status
    _running = False
    _status = None


async def archive_daily_klines(
    session_factory: async_sessionmaker[AsyncSession],
    tdx: TdxClient,
    trade_date: date,
    count: int = 250,
    on_progress=None,
) -> dict:
    """全市场日K回档：刷新清单 → 每只 daily_bars → upsert_daily_kline。幂等。"""
    stocks = await refresh_stock_universe(session_factory, tdx)
    total = len(stocks)
    ok, failed = 0, 0
    for i, s in enumerate(stocks, 1):
        try:
            bars = await tdx.daily_bars(s.code, count=count)
            if bars:
                async with session_factory() as session:
                    await upsert_daily_kline(session, s.secucode, bars)
                ok += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[kline_archive] {s.secucode} error: {e}")
            failed += 1
        if on_progress is not None:
            on_progress(i, total, failed)
    return {"trade_date": trade_date.strftime("%Y-%m-%d"), "total": total, "ok": ok, "failed": failed}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_kline_archive.py -v`
Expected: 1 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/kline_archive.py backend/tests/test_kline_archive.py
git commit -m "feat(kline-archive): 全市场日K回档"
```

---

## Task 6: 日K存档 API + scheduler + ArchivePage Card

**Files:**
- Modify: `backend/app/api/archive.py`（加 daily 端点）
- Modify: `backend/app/scheduler.py`（加 cron）
- Modify: `backend/app/schemas/archive.py`（如需复用 ArchiveStatusOut；否则新增）
- Modify: `frontend/src/api/archive.ts`、`frontend/src/pages/ArchivePage.tsx`

**Interfaces:**
- Consumes: Task 5 的 `archive_daily_klines` + 状态函数。
- Produces: `POST /api/archive/daily?count=250`（202，后台跑）、`GET /api/archive/daily/status`；前端 `triggerDailyKlineArchive(count)` / `getDailyKlineArchiveStatus()`。

- [ ] **Step 1: 写后端失败测试**

```python
# backend/tests/test_api_archive.py 追加（若文件不存在则新建，参照 test_api_market 结构）
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services import kline_archive


@pytest.mark.asyncio
async def test_daily_kline_archive_trigger_and_status(monkeypatch):
    async def _fake(session_factory, tdx, trade_date, count=250, on_progress=None):
        return {"trade_date": trade_date.strftime("%Y-%m-%d"), "total": 1, "ok": 1, "failed": 0}
    monkeypatch.setattr(kline_archive, "archive_daily_klines", _fake)
    kline_archive.reset_daily_kline_archive_state()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/archive/daily?count=10")
        assert r.status_code == 202
        assert "trade_date" in r.json()
        s = await ac.get("/api/archive/daily/status")
        assert s.status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_api_archive.py -k daily_kline -v`
Expected: FAIL（404 / 端点不存在）

- [ ] **Step 3: 后端实现（改 archive.py）**

在 `backend/app/api/archive.py` 顶部 import 加：
```python
from app.services.kline_archive import (
    archive_daily_klines,
    get_daily_kline_archive_status,
    is_daily_kline_archive_running,
    set_daily_kline_archive_running,
    set_daily_kline_archive_status,
)
```
在文件末尾追加（完全仿 `_run_archive` / `trigger_minute_archive` / `minute_archive_status`）：
```python
_daily_tasks: set[asyncio.Task] = set()


async def _run_daily_kline_archive(count: int) -> None:
    from datetime import date
    from app.services.minute_archive import _today_cst
    started = _now_ts()
    td = _today_cst()
    set_daily_kline_archive_status({
        "state": "running", "trade_date": td.strftime("%Y-%m-%d"),
        "total": 0, "done": 0, "ok": 0, "failed": 0,
        "started_at": started, "finished_at": None, "error": None,
    })
    tdx = TdxClient()
    try:
        def on_progress(done, total, failed):
            set_daily_kline_archive_status({
                "state": "running", "trade_date": td.strftime("%Y-%m-%d"),
                "total": total, "done": done, "ok": done - failed, "failed": failed,
                "started_at": started, "finished_at": None, "error": None,
            })
        result = await archive_daily_klines(SessionLocal, tdx, td, count=count, on_progress=on_progress)
        set_daily_kline_archive_status({
            "state": "done", "trade_date": result["trade_date"],
            "total": result["total"], "done": result["total"],
            "ok": result["ok"], "failed": result["failed"],
            "started_at": started, "finished_at": _now_ts(), "error": None,
        })
    except Exception as e:
        set_daily_kline_archive_status({
            "state": "error", "trade_date": td.strftime("%Y-%m-%d"),
            "total": 0, "done": 0, "ok": 0, "failed": 0,
            "started_at": started, "finished_at": _now_ts(), "error": str(e),
        })
    finally:
        tdx.close()
        set_daily_kline_archive_running(False)


@router.post("/daily", response_model=ArchiveTriggerResponse, status_code=202)
async def trigger_daily_kline_archive(count: int = Query(250, ge=10, le=1000)):
    if is_daily_kline_archive_running():
        raise HTTPException(status_code=409, detail="daily kline archive already running")
    set_daily_kline_archive_running(True)
    task = asyncio.create_task(_run_daily_kline_archive(count))
    _daily_tasks.add(task)
    task.add_done_callback(_daily_tasks.discard)
    td = _today_cst() if False else None  # 占位避免未用，实际下方返回用 status
    return ArchiveTriggerResponse(task_id=str(_now_ts()), trade_date=get_daily_kline_archive_status()["trade_date"])


@router.get("/daily/status", response_model=ArchiveStatusOut | None)
async def daily_kline_archive_status():
    return get_daily_kline_archive_status()
```
> 注：`trigger_daily_kline_archive` 返回值的 `trade_date` 取自刚设的 status；`_today_cst` 已在文件 import。去掉占位行 `td = ...`（仅示意，实现时直接 `from app.services.minute_archive import _today_cst` 后用 `_today_cst().strftime("%Y-%m-%d")`）。

- [ ] **Step 4: scheduler 加 cron（改 scheduler.py）**

在 `backend/app/scheduler.py` 顶部 import 加 `from app.services.kline_archive import archive_daily_klines`，新增函数：
```python
async def daily_kline_archive() -> None:
    """16:10 增量回档全市场日K（count=10 取近 10 日，幂等 upsert）。"""
    tdx = TdxClient()
    try:
        await archive_daily_klines(SessionLocal, tdx, _today_cst(), count=10)
    finally:
        tdx.close()
```
在 `build_scheduler()` 的 `return sched` 前加：
```python
    sched.add_job(daily_kline_archive, CronTrigger(hour=16, minute=10), id="daily_kline_archive")
```

- [ ] **Step 5: 前端 api + Card**

`frontend/src/api/archive.ts` 追加：
```typescript
export const triggerDailyKlineArchive = (count = 250) =>
  apiPost<{ task_id: string; trade_date: string }>(`/archive/daily?count=${count}`);
export const getDailyKlineArchiveStatus = () =>
  apiGet<ArchiveStatus | null>("/archive/daily/status");
```
`frontend/src/pages/ArchivePage.tsx`：复制现有"分时行情存档"Card 的结构（state/useEffect 轮询/trigger/进度），改用 `triggerDailyKlineArchive` / `getDailyKlineArchiveStatus`，title="日K回档"，文案"回档全市场日K（默认 250 根，每日 16:10 增量）"。作为第三个 Card。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_api_archive.py -k daily_kline -v && cd ../frontend && npm run build`
Expected: 后端测试 PASS；前端 build 通过

- [ ] **Step 7: 提交**

```bash
git add backend/app/api/archive.py backend/app/scheduler.py backend/tests/test_api_archive.py \
        frontend/src/api/archive.ts frontend/src/pages/ArchivePage.tsx
git commit -m "feat(archive): 日K存档 API + scheduler 16:10 + ArchivePage Card"
```

---

## Task 7: 选股筛选器 API

**Files:**
- Create: `backend/app/schemas/screener.py`
- Create: `backend/app/api/screener.py`
- Modify: `backend/app/main.py`（注册 router）
- Test: `backend/tests/test_api_screener.py`

**Interfaces:**
- Consumes: Task 2/3/4 的 `compute_indicators` / `score` / `signal_level` / `evaluate_extras`；`models.kline.DailyKline`。
- Produces: `POST /api/screener` body `{signal?, extras?, sort?}` → `[{secucode,name,close,pct,score,signal,macd,kdj,wr,rsi}]`。`signal` 缺省不过滤；`sort` 缺省 `score_desc`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_api_screener.py
import pytest
from datetime import date
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.stock import StockMeta
from app.models.kline import DailyKline


async def _seed(db_session, code, name, closes):
    """写 N 根日K（close 序列），secucode 由 code 推。"""
    suf = "SH" if code.startswith("6") else "SZ"
    db_session.add(StockMeta(secucode=f"{code}.{suf}", code=code, name=name,
                             market=suf, secid=f"{'1' if suf=='SH' else '0'}.{code}"))
    await db_session.commit()
    for i, c in enumerate(closes):
        db_session.add(DailyKline(
            ts=date(2026, 6, 1 + i), secucode=f"{code}.{suf}",
            open=c, close=c, high=c * 1.01, low=c * 0.99, volume=1000,
            amount=c * 100000, turnover_rate=0.0, pct_change=0.0, vwap=c))
    await db_session.commit()


@pytest.mark.asyncio
async def test_screener_filters_strong_bull(db_session):
    await _seed(db_session, "600519", "贵州茅台", [100 + i for i in range(30)])  # 持续涨→强多
    await _seed(db_session, "000001", "平安银行", [100 - i for i in range(30)])  # 持续跌
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/screener", json={"signal": "strong_bull"})
    assert r.status_code == 200
    data = r.json()
    codes = [d["secucode"] for d in data]
    assert "600519.SH" in codes and "000001.SZ" not in codes
    hit = next(d for d in data if d["secucode"] == "600519.SH")
    assert hit["score"] >= 3 and hit["signal"] == "strong_bull"
    assert set(hit) >= {"macd", "kdj", "wr", "rsi"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_api_screener.py -v`
Expected: FAIL（404）

- [ ] **Step 3: 写 schema**

```python
# backend/app/schemas/screener.py
from pydantic import BaseModel


class ExtraCondition(BaseModel):
    type: str
    n: int | None = None
    k: float | None = None
    lo: float | None = None
    hi: float | None = None


class ScreenRequest(BaseModel):
    signal: str | None = None  # strong_bull/bull/neutral/bear/strong_bear
    extras: list[ExtraCondition] = []
    sort: str = "score_desc"


class ScreenItem(BaseModel):
    secucode: str
    name: str
    close: float
    pct: float
    score: int
    signal: str
    macd: int
    kdj: int
    wr: int
    rsi: int
```

- [ ] **Step 4: 写 router**

```python
# backend/app/api/screener.py
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.schemas.screener import ScreenRequest, ScreenItem
from app.services.indicator import (
    compute_indicators, score, signal_level, evaluate_extras,
    macd_signal, kdj_signal, wr_signal, rsi_signal,
)

router = APIRouter(prefix="/api/screener", tags=["screener"])
_N = 60  # 每只取近 60 根


@router.post("", response_model=list[ScreenItem])
async def screen(req: ScreenRequest, session: AsyncSession = Depends(get_db)):
    rows = (await session.execute(
        select(DailyKline.ts, DailyKline.secucode, DailyKline.open, DailyKline.close,
               DailyKline.high, DailyKline.low, DailyKline.volume, DailyKline.pct_change)
        .order_by(DailyKline.secucode, DailyKline.ts)
    )).all()
    names = {s.secucode: s.name for s in (await session.execute(select(StockMeta))).scalars()}

    grouped: dict[str, list] = defaultdict(list)
    for ts, secucode, o, c, h, low, vol, pct in rows:
        grouped[secucode].append((ts, float(o), float(c), float(h), float(low), int(vol), float(pct)))

    out = []
    for secucode, lst in grouped.items():
        lst = lst[-_N:]
        if len(lst) < 30:
            continue
        from app.services.collector.types import KlineBar
        bars = [KlineBar(str(ts.date()), o, c, h, low, vol, 0.0, pct, 0.0, c) for ts, o, c, h, low, vol, pct in lst]
        ind = compute_indicators(bars)
        s = score(ind)
        lvl = signal_level(s)
        if req.signal and lvl != req.signal:
            continue
        if not evaluate_extras(ind, [e.model_dump() for e in req.extras]):
            continue
        out.append(ScreenItem(
            secucode=secucode, name=names.get(secucode, secucode),
            close=ind["close"], pct=bars[-1].pct_change if False else float(lst[-1][6]),
            score=s, signal=lvl,
            macd=macd_signal(ind), kdj=kdj_signal(ind), wr=wr_signal(ind), rsi=rsi_signal(ind),
        ))
    out.sort(key=lambda x: x.score, reverse=(req.sort == "score_desc"))
    return out
```
> 注：`pct` 用 `lst[-1][6]`（最后一根的 pct_change）；去掉示意性的 `bars[-1].pct_change if False else`，直接 `float(lst[-1][6])`。

- [ ] **Step 5: 注册 router（改 main.py）**

`backend/app/main.py` 顶部 import 加 `from app.api.screener import router as screener_router`，在 `app.include_router(market_router)` 后加 `app.include_router(screener_router)`。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_api_screener.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add backend/app/schemas/screener.py backend/app/api/screener.py backend/app/main.py backend/tests/test_api_screener.py
git commit -m "feat(screener): 选股筛选器 API（共振多空 + 辅助条件）"
```

---

## Task 8: 指标时序接口（供副图）

**Files:**
- Modify: `backend/app/services/indicator.py`（加 `indicator_series`）
- Modify: `backend/app/api/stocks.py`（加端点）
- Test: `backend/tests/test_api_stocks.py`（追加）

**Interfaces:**
- Consumes: `DailyKline` + `_calc_arrays`。
- Produces: `indicator_series(bars) -> list[dict]`（每根 `{date,dif,dea,hist,k,d,j,wr,rsi,close}`）；`GET /api/stocks/{code}/indicators?count=60`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_api_stocks.py 追加
import pytest
from datetime import date
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.stock import StockMeta
from app.models.kline import DailyKline


@pytest.mark.asyncio
async def test_stock_indicators_series(db_session):
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()
    for i in range(60):
        db_session.add(DailyKline(ts=date(2026, 6, 1 + i), secucode="600519.SH",
                                  open=100, close=100 + i, high=101 + i, low=99, volume=1000,
                                  amount=1e7, turnover_rate=0, pct_change=1.0, vwap=100))
    await db_session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/api/stocks/600519.SH/indicators?count=60")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 60
    assert set(data[-1]) >= {"date", "dif", "dea", "hist", "k", "d", "j", "wr", "rsi", "close"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_api_stocks.py -k indicators_series -v`
Expected: FAIL（404）

- [ ] **Step 3: indicator_series（追加到 indicator.py）**

```python
# 追加到 backend/app/services/indicator.py
def indicator_series(bars) -> list[dict]:
    """每根日K的指标时序（副图用）。"""
    a = _calc_arrays(bars)
    dates = [getattr(b, "date", str(i)) for i, b in enumerate(bars)]
    out = []
    for i in range(len(a["closes"])):
        out.append({
            "date": dates[i], "close": float(a["closes"][i]),
            "dif": float(a["dif"][i]), "dea": float(a["dea"][i]), "hist": float(a["hist"][i]),
            "k": float(a["k"][i]), "d": float(a["d"][i]), "j": float(a["j"][i]),
            "wr": float(a["wr"][i]), "rsi": float(a["rsi"][i]),
        })
    return out
```

- [ ] **Step 4: 端点（追加到 api/stocks.py，仿现有 K 线查询模式）**

```python
# 追加到 backend/app/api/stocks.py
from app.services.indicator import indicator_series

@router.get("/{secucode}/indicators", response_model=list[dict])
async def stock_indicators(secucode: str, count: int = 60, session: AsyncSession = Depends(get_db)):
    rows = (await session.execute(
        select(DailyKline).where(DailyKline.secucode == secucode)
        .order_by(DailyKline.ts.desc()).limit(count)
    )).scalars().all()
    rows = list(reversed(rows))
    if not rows:
        raise HTTPException(status_code=404, detail="no kline")
    from app.services.collector.types import KlineBar
    bars = [KlineBar(str(r.ts.date()), float(r.open), float(r.close), float(r.high),
                     float(r.low), int(r.volume), float(r.amount), float(r.pct_change),
                     float(r.turnover_rate), float(r.vwap)) for r in rows]
    return indicator_series(bars)
```
> 注：确认 `api/stocks.py` 已 import `DailyKline` / `select` / `AsyncSession` / `get_db` / `HTTPException` / `router`；若缺则补 import（参照文件现有 K 线端点）。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. python -m pytest tests/test_api_stocks.py -k indicators_series -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/indicator.py backend/app/api/stocks.py backend/tests/test_api_stocks.py
git commit -m "feat(stocks): 指标时序接口（副图用）"
```

---

## Task 9: ScreenerPage 前端

**Files:**
- Create: `frontend/src/api/screener.ts`
- Create: `frontend/src/pages/ScreenerPage.tsx`
- Modify: `frontend/src/App.tsx`（路由）+ `frontend/src/components/AppLayout.tsx`（导航项）
- Test: `frontend/src/pages/ScreenerPage.test.tsx`

**Interfaces:**
- Consumes: `POST /api/screener`（Task 7）；`apiPost`。
- Produces: `/screener` 页面：左条件面板（信号下拉 + 辅助条件勾选）右结果表（综合分排序 + 四指标 ▲▼—）。

- [ ] **Step 1: 写失败测试**

```typescript
// frontend/src/pages/ScreenerPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import ScreenerPage from "./ScreenerPage";

const server = setupServer(
  http.post("/api/screener", () =>
    HttpResponse.json([
      { secucode: "600519.SH", name: "贵州茅台", close: 1680, pct: 1.2,
        score: 4, signal: "strong_bull", macd: 1, kdj: 1, wr: 1, rsi: 1 },
    ])
  )
);
beforeAll(() => server.listen());
afterAll(() => server.close());

test("renders screener results with score and signals", async () => {
  render(<MemoryRouter><ScreenerPage /></MemoryRouter>);
  // 默认查 strong_bull，点查询后出现茅台
  await waitFor(() => expect(screen.getByText("贵州茅台")).toBeInTheDocument());
  expect(screen.getByText("4")).toBeInTheDocument();
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/ScreenerPage.test.tsx`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写 api 层**

```typescript
// frontend/src/api/screener.ts
import { apiPost } from "./client";

export interface ExtraCondition { type: string; n?: number; k?: number; lo?: number; hi?: number; }
export interface ScreenRequest { signal?: string; extras?: ExtraCondition[]; sort?: string; }
export interface ScreenItem {
  secucode: string; name: string; close: number; pct: number;
  score: number; signal: string; macd: number; kdj: number; wr: number; rsi: number;
}
export const screenStocks = (req: ScreenRequest) => apiPost<ScreenItem[]>("/screener", req);
```

- [ ] **Step 4: 写 ScreenerPage**

```tsx
// frontend/src/pages/ScreenerPage.tsx
import { useState } from "react";
import { Button, Checkbox, Select, Space, Table, Typography, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useNavigate } from "react-router-dom";
import { screenStocks, type ScreenItem, type ExtraCondition } from "../api/screener";

const { Text } = Typography;
const SIGNALS = ["strong_bull", "bull", "neutral", "bear", "strong_bear"];
const SIGNAL_LABEL: Record<string, string> = {
  strong_bull: "强多", bull: "偏多", neutral: "中性", bear: "偏空", strong_bear: "强空",
};

function Arrow({ v }: { v: number }) {
  const c = v > 0 ? "#f5222d" : v < 0 ? "#16a34a" : "#9ca3af";
  const s = v > 0 ? "▲" : v < 0 ? "▼" : "—";
  return <span style={{ color: c }}>{s}</span>;
}

export default function ScreenerPage() {
  const [signal, setSignal] = useState<string>("strong_bull");
  const [extras, setExtras] = useState<Record<string, boolean>>({ ma_bull: false, breakout: false, volume_up: false });
  const [data, setData] = useState<ScreenItem[]>([]);
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();

  const run = async () => {
    setLoading(true);
    try {
      const ex: ExtraCondition[] = (["ma_bull", "breakout", "volume_up"] as const)
        .filter((k) => extras[k]).map((k) => k === "breakout" ? { type: "breakout", n: 20 } : { type: k });
      setData(await screenStocks({ signal, extras: ex }));
    } catch (e: any) { message.error(String(e?.message || e)); }
    finally { setLoading(false); }
  };

  const columns: ColumnsType<ScreenItem> = [
    { title: "代码", dataIndex: "secucode", render: (v, r) => <a onClick={() => nav(`/stock/${v}`)}>{v}</a> },
    { title: "名称", dataIndex: "name" },
    { title: "现价", dataIndex: "close", align: "right", render: (v: number) => v.toFixed(2) },
    { title: "涨幅", dataIndex: "pct", align: "right", render: (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` },
    { title: "综合分", dataIndex: "score", align: "right", sorter: (a, b) => a.score - b.score,
      render: (v: number) => <Text strong>{v}</Text> },
    { title: "信号", dataIndex: "signal", render: (v: string) => SIGNAL_LABEL[v] || v },
    { title: "MACD", dataIndex: "macd", align: "center", render: (v: number) => <Arrow v={v} /> },
    { title: "KDJ", dataIndex: "kdj", align: "center", render: (v: number) => <Arrow v={v} /> },
    { title: "WR", dataIndex: "wr", align: "center", render: (v: number) => <Arrow v={v} /> },
    { title: "RSI", dataIndex: "rsi", align: "center", render: (v: number) => <Arrow v={v} /> },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Space wrap>
        <Select value={signal} onChange={setSignal} style={{ width: 120 }}
                options={SIGNALS.map((s) => ({ value: s, label: SIGNAL_LABEL[s] }))} />
        <Checkbox checked={extras.ma_bull} onChange={(e) => setExtras({ ...extras, ma_bull: e.target.checked })}>均线多头</Checkbox>
        <Checkbox checked={extras.breakout} onChange={(e) => setExtras({ ...extras, breakout: e.target.checked })}>突破20日</Checkbox>
        <Checkbox checked={extras.volume_up} onChange={(e) => setExtras({ ...extras, volume_up: e.target.checked })}>放量</Checkbox>
        <Button type="primary" loading={loading} onClick={run}>筛选</Button>
      </Space>
      <Table size="small" rowKey="secucode" columns={columns} dataSource={data} pagination={{ pageSize: 50 }} />
    </Space>
  );
}
```

- [ ] **Step 5: 路由 + 导航**

`frontend/src/App.tsx`：import `ScreenerPage`，在 `<Route path="/market" .../>` 后加 `<Route path="/screener" element={<ScreenerPage />} />`。
`frontend/src/components/AppLayout.tsx`：在导航菜单（参照现有 market/archive 项）加一项 `{ key: "/screener", label: "选股" }`。

- [ ] **Step 6: 跑测试 + build**

Run: `cd frontend && npx vitest run src/pages/ScreenerPage.test.tsx && npm run build`
Expected: 测试 PASS；build 通过

- [ ] **Step 7: 提交**

```bash
git add frontend/src/api/screener.ts frontend/src/pages/ScreenerPage.tsx \
        frontend/src/pages/ScreenerPage.test.tsx frontend/src/App.tsx frontend/src/components/AppLayout.tsx
git commit -m "feat(screener): ScreenerPage 前端（条件面板 + 结果表）"
```

---

## Task 10: StockDetail 四大指标副图

**Files:**
- Create: `frontend/src/components/IndicatorCharts.tsx`
- Modify: `frontend/src/pages/StockDetail.tsx`
- Test: `frontend/src/components/IndicatorCharts.test.tsx`

**Interfaces:**
- Consumes: `GET /api/stocks/{code}/indicators?count=60`（Task 8）；ECharts。
- Produces: `<IndicatorCharts secucode={...} />`，渲染 MACD/KDJ/WR/RSI 四副图。

- [ ] **Step 1: 写失败测试**

```typescript
// frontend/src/components/IndicatorCharts.test.tsx
import { render, waitFor, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import IndicatorCharts from "./IndicatorCharts";

const server = setupServer(
  http.get("/api/stocks/600519.SH/indicators", () =>
    HttpResponse.json([
      { date: "2026-06-01", close: 100, dif: 1, dea: 0.5, hist: 1, k: 50, d: 50, j: 50, wr: 50, rsi: 50 },
    ]))
);
beforeAll(() => server.listen());
afterAll(() => server.close());

test("renders four indicator panels", async () => {
  render(<IndicatorCharts secucode="600519.SH" />);
  await waitFor(() => expect(screen.getByText("MACD")).toBeInTheDocument());
  expect(screen.getByText("KDJ")).toBeInTheDocument();
  expect(screen.getByText("WR")).toBeInTheDocument();
  expect(screen.getByText("RSI")).toBeInTheDocument();
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/IndicatorCharts.test.tsx`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写组件**

```tsx
// frontend/src/components/IndicatorCharts.tsx
import { useEffect, useState } from "react";
import { Card, Col, Row } from "antd";
import ReactECharts from "echarts-for-react";
import { apiGet } from "../api/client";

interface Pt { date: string; close: number; dif: number; dea: number; hist: number;
  k: number; d: number; j: number; wr: number; rsi: number; }

function pane(title: string, xs: string[], series: any[]) {
  return (
    <Card size="small" title={title} styles={{ body: { height: 180 } }}>
      <ReactECharts style={{ height: 160 }} option={{
        tooltip: { trigger: "axis" }, xAxis: { type: "category", data: xs, axisLabel: { show: false } },
        yAxis: { type: "value", scale: true }, legend: { top: 0, textStyle: { fontSize: 10 } }, series,
      }} />
    </Card>
  );
}

export default function IndicatorCharts({ secucode }: { secucode: string }) {
  const [pts, setPts] = useState<Pt[]>([]);
  useEffect(() => {
    let cancel = false;
    apiGet<Pt[]>(`/stocks/${secucode}/indicators`, { count: "60" })
      .then((d) => { if (!cancel) setPts(d); }).catch(() => { if (!cancel) setPts([]); });
    return () => { cancel = true; };
  }, [secucode]);
  if (!pts.length) return null;
  const xs = pts.map((p) => p.date);
  const line = (key: keyof Pt, color: string) => ({ name: key.toString().toUpperCase(), type: "line", data: pts.map((p) => p[key] as number), showSymbol: false, lineStyle: { width: 1.2, color } });
  return (
    <Row gutter={[8, 8]} style={{ marginTop: 8 }}>
      <Col span={12}>{pane("MACD", xs, [
        { ...line("dif", "#f5222d") }, { ...line("dea", "#16a34a") },
        { name: "HIST", type: "bar", data: pts.map((p) => p.hist) },
      ])}</Col>
      <Col span={12}>{pane("KDJ", xs, [
        { ...line("k", "#f5222d") }, { ...line("d", "#16a34a") }, { ...line("j", "#5b6cff") },
      ])}</Col>
      <Col span={12}>{pane("WR", xs, [line("wr", "#5b6cff")])}</Col>
      <Col span={12}>{pane("RSI", xs, [line("rsi", "#5b6cff")])}</Col>
    </Row>
  );
}
```

- [ ] **Step 4: 接入 StockDetail**

`frontend/src/pages/StockDetail.tsx`：import `IndicatorCharts from "../components/IndicatorCharts"`，在 `<KLineChart bars={kline} />` 下方插入 `<IndicatorCharts secucode={secucode} />`。

- [ ] **Step 5: 跑测试 + build**

Run: `cd frontend && npx vitest run src/components/IndicatorCharts.test.tsx && npm run build`
Expected: 测试 PASS；build 通过

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/IndicatorCharts.tsx frontend/src/components/IndicatorCharts.test.tsx \
        frontend/src/pages/StockDetail.tsx
git commit -m "feat(stock-detail): 四大指标副图（MACD/KDJ/WR/RSI）"
```

---

## Self-Review

**1. Spec 覆盖**
- 四大指标计算 → Task 2 ✓；信号 + 共振 → Task 3 ✓；辅助条件 → Task 4 ✓；日K回灌 + 调度 → Task 5/6 ✓；筛选器 API → Task 7 ✓；ScreenerPage → Task 9 ✓；StockDetail 副图 → Task 8/10 ✓；测试 → 每任务内 ✓。
- 阶段 2（物化表、全市场筹码）明确不在本计划（spec 非目标）✓。

**2. 占位扫描**
- Task 6/7/8 含 `if False else` / `td = ... if False else None` 等**示意占位**——已在注释中标明实现时去掉、直接用正确表达式。执行者须按注释改为最终代码（已在对应 Step 注明）。除这些明确标注的之外无 TBD/TODO。

**3. 类型/命名一致性**
- `compute_indicators` 字段在 Task 2 定义，Task 3/4 信号与谓词、Task 7/8 使用一致（`dif/dea/k/d/j/wr/rsi/prev_rsi/ma5..60/ma20_prev5/high20_prev/high60_prev/vol_ratio/pct5/consecutive_green/close/open`）✓。
- `score`/`signal_level` Task 3 定义、Task 7 使用一致 ✓。
- `evaluate_extras` Task 4 定义、Task 7 使用一致 ✓。
- `indicator_series` Task 8 定义、Task 10 使用一致 ✓。
- 前端 `ScreenItem` 字段 Task 9 与后端 `ScreenItem` schema（Task 7）一致 ✓。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-24-stock-screener.md`. Two execution options:

**1. Subagent-Driven (recommended)** — 每个 Task 派一个全新 subagent 实现，任务间我做两段式 review，迭代快、上下文干净。

**2. Inline Execution** — 在本会话用 executing-plans 批量执行，带 checkpoint 审查。

选哪种？
