# 盘后技术选股筛选器（MACD/KDJ/WR/RSI 四大指标共振多空）

## Context（为什么做）

当前"行情页"（分时概览 + 涨跌榜）只能展示**当天**涨跌，无法用来分析"哪些股票接下来要涨/跌"。用户需要的是**盘后跨日选股**：基于 K 线技术面（筹码辅助），对**全市场**做条件筛选，直观地筛出有上涨潜力的标的。

核心方法论（用户确定）：结合 **MACD、KDJ、WR、RSI** 四大经典技术指标，用**共振表决**综合判断个股多空信号，作为筛选器的主筛依据；均线/突破/放量等作为可叠加的辅助条件。

ChipScope 现状（约束）：
- `daily_kline` 表 + `upsert_daily_kline(session, secucode, bars)`（`ingest.py:30`）已存在，但只对自选股/单股按需存，**全市场日K未批量入库**。
- **无任何技术指标计算代码**（MACD/KDJ/WR/RSI/均线都要从零写）。
- 筹码指标（`chip_metrics.py`）有，但只算自选股。
- `TdxClient.daily_bars(symbol, count)` 可拉日K（升序、`KlineBar.date` 为 `YYYY-MM-DD`）。
- 后台采集已有成熟模式：`archive_minute_quotes`（`minute_archive.py`）+ 进度状态 + ArchivePage 触发，可仿写。

## 目标 / 非目标

**阶段 1 目标（本次实现）**
1. 全市场日K回灌入库（一次性 + 每日增量）。
2. `indicator.py` 纯函数：计算 MACD/KDJ/WR/RSI + 均线/突破/放量，并产出共振多空信号。
3. 筛选器 API `POST /api/screener`：按综合信号筛 + 辅助条件 + 排序。
4. 筛选器 UI `ScreenerPage`：综合信号 + 辅助条件面板、结果表（四指标多空着色）。
5. `StockDetail` 加四大指标副图，供人工复核信号。

**非目标（阶段 1 不做，留阶段 2）**
- 指标物化表 `stock_metric`（阶段 1 筛选时实时算）。
- 全市场筹码采集 + 筹码辅助条件（获利盘/集中度）。
- 复杂形态识别（W 底、头肩等）、相对强度排名。
- 盘中实时（本特性面向盘后）。

## 整体架构

```
全市场日K回灌   mootdx daily_bars → daily_kline（复用 upsert_daily_kline）
                      │
indicator.py 纯函数  compute_indicators(bars) → {macd,kdj,wr,rsi,ma...,signal,score}
                      │   阶段1：筛选时实时算每只近60根
                      │ ──阶段2物化──▶ stock_metric 表（每日更新，秒级查询）
                      │
筛选器 API     POST /api/screener  →  匹配股票列表（含综合分 + 四指标信号）
                      │
ScreenerPage   左：综合信号 + 辅助条件面板   右：结果表（综合分排序，四指标 ▲▼— 着色）
                      └─ 点行 → StockDetail（K线 + 四大指标副图 + 筹码火焰图 复核）
```

## 两阶段划分

- **阶段 1（先交付、先验证）**：日K回灌 + 指标纯函数 + 筛选器从 `daily_kline` **实时算**（每只取近 60 根向量化算，全市场预计几秒）+ StockDetail 四大指标副图。目的：验证四大指标共振 + 辅助条件的选股效果。
- **阶段 2（性能 + 深度）**：指标**物化**到 `stock_metric` 表（每日调度更新）→ 筛选器查表秒级任意组合 → 加**筹码辅助条件**（需把筹码采集从自选扩到全市场）。

## 数据模型

- `daily_kline`（已有，`models/kline.py`）：扩到全市场，**无 schema 改动**。
- `stock_metric`（**新，阶段 2**）：`secucode, trade_date, macd_signal, kdj_signal, wr_signal, rsi_signal, score, ma5/10/20/60, high20/60, vol_ratio, ...`，每日 upsert。阶段 1 不建此表。

## 技术指标计算（`services/indicator.py`，纯 NumPy，仿 `chip_engine` 风格）

纯函数 `compute_indicators(bars: list[KlineBar]) -> dict`，输入近 N 根日K（默认取 60，含当日），输出所有指标快照。所有辅助函数（EMA/SMA/HHV/LLV）显式定义以保证可测、无歧义。

**EMA**：`EMA[t] = α·x[t] + (1-α)·EMA[t-1]`，`α = 2/(N+1)`，`EMA[0] = x[0]`。
**SMA（通达信）**：`SMA[t] = (SMA[t-1]·(M-1) + x[t])/M`，`SMA[0] = x[0]`。
**HHV/LLV**：过去 N 根（含当根）最高/最低。

| 指标 | 参数 | 公式 |
|---|---|---|
| MACD | 12,26,9 | `DIF = EMA(c,12) - EMA(c,26)`；`DEA = EMA(DIF,9)`；`HIST = (DIF-DEA)·2` |
| KDJ | 9,3,3 | `RSV = (c - LLV(l,9)) / (HHV(h,9) - LLV(l,9)) · 100`；`K = SMA(RSV,3)`；`D = SMA(K,3)`；`J = 3K - 2D`（**初始 K=D=50**，通达信标准） |
| WR | 14 | `WR = (HHV(h,14) - c) / (HHV(h,14) - LLV(l,14)) · 100` |
| RSI | 6 | `RS = mean(up) / mean(down)`（6 日平均涨/跌幅，跌为 0 时按 0 处理）；`RSI = 100 - 100/(1+RS)` |
| MA | 5/10/20/60 | 简单移动平均 |
| 量比 | 5 | `vol_ratio = vol[t] / mean(vol, 5)` |

## 信号规则 + 共振表决

每个指标对**当日**输出 `+1（多）/ 0（中性）/ -1（空）`：

| 指标 | 看多 (+1) | 看空 (-1) | 中性 (0) |
|---|---|---|---|
| MACD | `DIF > DEA` **且** `DIF > 0` | `DIF < DEA` **且** `DIF < 0` | 其他 |
| KDJ | `K > D` **且** `J < 50`（低位金叉）**或** `J < 20`（超卖） | `K < D` **且** `J > 80`（超买） | 其他 |
| WR | `WR > 80`（超卖） | `WR < 20`（超买） | `20 ≤ WR ≤ 80` |
| RSI | `RSI < 30`（超卖）**或** 上穿 50（`RSI[t]≥50 且 RSI[t-1]<50`） | `RSI > 70`（超买） | `30 ≤ RSI ≤ 70` |

**共振综合**：`score = macd + kdj + wr + rsi ∈ [-4, +4]`，分档：

| score | 信号 |
|---|---|
| `+3, +4` | `strong_bull` 强多 |
| `+1, +2` | `bull` 偏多 |
| `0` | `neutral` 中性 |
| `-1, -2` | `bear` 偏空 |
| `-3, -4` | `strong_bear` 强空 |

> WR 方向已统一为"WR 大 = 超卖 = 看多"（最易搞反处）；KDJ 用 `J<50` 过滤高位金叉。

## 辅助条件集（可叠加，AND）

每条是"指标快照上的谓词"，默认参数可调：

| 类型 | 条件 | 默认参数 |
|---|---|---|
| `ma_bull` | MA5 > MA10 > MA20 > MA60 | 固定 |
| `above_ma` | `close > MA(N)` | N=20（可选 20/60） |
| `ma_up` | `MA20[t] > MA20[t-5]` | 回看 5 |
| `breakout` | `close > max(high[-N-1:-1])`（不含今） | N=20（可选 20/60） |
| `new_high` | `close ≥ max(high[-N:]) · 0.98` | N=60 |
| `volume_up` | `vol_ratio > k` | k=2.0 |
| `volume_up_green` | `volume_up` 且 `close > open` | k=2.0 |
| `pct_range` | `close/close[-N]-1 ∈ [lo,hi]` | N=5, [3%,15%] |
| `consecutive_green` | 连续 `close>open` 天数 ≥ k | k=3 |

## 日K回灌 + 调度

- 新增 `services/kline_archive.py`，仿 `minute_archive.py`：
  - `archive_daily_klines(session_factory, tdx, trade_date, on_progress)`：遍历全市场 A 股（复用 `_filter_a_shares`/`refresh_stock_universe`），对每只 `daily_bars(code, count=250)` → `upsert_daily_kline`。幂等（ON CONFLICT）。
  - 进程内状态 + `reset_archive_state()`，同 `minute_archive` 模式。
- API `POST /api/archive/daily`（仿 `trigger_minute_archive`）+ `GET /api/archive/daily/status`。
- 前端 ArchivePage 新增第三个 Card"日K回档"（默认当天增量；可选历史回灌窗口）。
- 调度：`scheduler.py` 每日收盘后增量更新（与分时存档并列）。

## 筛选器 API

`POST /api/screener`
```jsonc
// 请求
{ "signal": "strong_bull",
  "extras": [{"type":"ma_bull"}, {"type":"breakout","n":20}],
  "sort": "score_desc" }
// 响应
[{ "secucode":"600519.SH","name":"贵州茅台","close":1680.0,"pct":1.2,
   "score":3,"signal":"strong_bull",
   "macd":1,"kdj":1,"wr":0,"rsi":1 }]
```
实现：查 `daily_kline` 全市场每只近 60 根 → `compute_indicators` → 共振 `score`/`signal` → 筛 `signal`（命中）→ 叠加 `extras` 谓词（AND）→ 按 `sort` 排序。阶段 1 实时算。

## UI

- **新页 `ScreenerPage`**（导航加"选股"入口）：
  - 左：综合信号下拉（强多/偏多/中性/偏空/强空）+ 辅助条件勾选 + 参数。
  - 右：结果表，按 `score` 排序，每行用 ▲(红,多)/▼(绿,空)/—(灰,中性) 着色标 MACD/KDJ/WR/RSI 四列，一眼看共振；列含现价、涨幅、综合分。点行 → StockDetail。
- **`StockDetail` 四大指标副图**：K 线下方加 MACD（DIF/DEA/HIST）、KDJ（K/D/J）、WR、RSI 四个 ECharts 副图，与筛选信号同源（同一 `compute_indicators`），供人工复核。

## 测试策略

- `tests/test_indicator.py`（纯函数）：
  - EMA/SMA/HHV/LLV 辅助函数对照手算值。
  - MACD：构造 DIF 上穿 DEA 序列验信号；KDJ：构造超卖（J<20）/低位金叉；WR：边界 80/20；RSI：超买超卖边界、上穿50。
  - 共振 `score`/`signal` 分档：覆盖 -4..+4 各组合。
- `tests/test_api_screener.py`：fake 日K数据，验 signal 筛选 + extras 叠加 + 排序。
- `tests/test_kline_archive.py`：fake TdxClient（仿 `test_minute_archive` 的 `_FakeArchiveTdx`），验回灌 upsert + 进度 + failed 计数。
- 前端 `ScreenerPage.test.tsx` + StockDetail 副图 vitest。

## 阶段 1 交付清单

1. `services/indicator.py`（纯函数 + 辅助函数 + 信号 + 共振 + 辅助条件谓词）
2. `services/kline_archive.py` + `api/archive.py` 新端点 + ArchivePage Card + scheduler 增量
3. `api/screener.py`（新 router）+ schema
4. `ScreenerPage` 新页 + 导航 + api 层
5. `StockDetail` 四大指标副图
6. 上述测试
