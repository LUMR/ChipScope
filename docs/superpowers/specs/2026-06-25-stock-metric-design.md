# stock_metric 指标物化表（选股筛选器阶段2：性能加速）

## Context（为什么做）

阶段1 的选股筛选器（`POST /api/screener`）在筛选时对全市场 ~5400 股**每只实时算** `compute_indicators`（取近 60 根日K → MACD/KDJ/WR/RSI + 均线 + 信号），单次筛选 5-15 秒。瓶颈是 `indicator.py` 辅助函数（`ema`/`sma_tdx` 的 Python for 循环、`hhv`/`llv` 的 Python for + `np.max/min`）乘以 5400 股，Python 解释器 + numpy 调用开销叠加。盘后选股体验差。

阶段2 把指标计算从"查询时实时算"改为"盘后预计算物化到 `stock_metric` 表，查询时直接查表"，筛选从 5-15s 降到 <200ms；同时统一 screener 与 StockDetail 副图的数据源（都查 `stock_metric`）。

## 目标 / 非目标

**目标（本次）**
1. 新建 `stock_metric` 表：每股每日一行，存 `compute_indicators` 全快照 + `score`/`signal_level`/四信号。
2. 预计算服务 `metric_archive.py`：每日盘后（16:15，紧接日K回档后）全市场增量预计算 + upsert；支持手动历史回填。
3. screener 改查 `stock_metric` 最新日（O(5400) 查表 <200ms），保留 `evaluate_extras` 动态组合。
4. 副图（`indicator_series`）改查 `stock_metric` 历史时序，不足时回退实时算。
5. 手动回填 API + ArchivePage Card（首次部署回填历史）。

**非目标（本次不做）**
- 向量化 `compute_indicators` 本身（预计算仍用现有 Python 循环，盘后跑可接受；向量化留 follow-up）。
- 筹码辅助条件扩到全市场（独立 feature）。
- 盘中实时刷新指标（本特性面向盘后）。

## 整体架构

```
daily_kline（已有，全市场日K）
    │  ① 16:15 cron（紧接 16:10 daily_kline_archive 之后，确保当日K已入库）
    ▼
metric_archive.archive_daily_metrics：每股取近 60 根 → compute_indicators → upsert stock_metric
    │
stock_metric（新表：每股每日一行，全指标 + score/signal）
    │
    ├── ② screener：SELECT 最新 trade_date 全量 → score/signal(已物化) → evaluate_extras(动态) → filter → sort   O(5400) <200ms
    └── ③ 副图：  SELECT WHERE secucode ORDER BY trade_date DESC LIMIT count（不足回退实时算）
```

## 数据模型

新建 `stock_metric` 表（`models/stock_metric.py` + alembic migration 0008）：

- **主键**: `(trade_date DATE, secucode VARCHAR(12) FK→stock_meta.secucode)`
- **索引**: `ix_stock_metric_secucode_trade_date (secucode, trade_date)`（副图按 secucode 查时序）
- **字段**（Numeric，仿 `DailyKline` 精度）：
  - 快照（`compute_indicators` 全字段）：`close, open, dif, dea, hist, k, d, j, wr, rsi, prev_rsi, ma5, ma10, ma20, ma60, ma20_prev5, high20_prev, high60_prev, vol_ratio, pct5, consecutive_green`
  - 派生信号：`score(INT), signal_level(VARCHAR), macd_signal(INT), kdj_signal(INT), wr_signal(INT), rsi_signal(INT)`
- upsert：`ON CONFLICT (trade_date, secucode) DO UPDATE`（幂等，重跑覆盖）

## 预计算服务 `services/metric_archive.py`（仿 `kline_archive.py`）

- `archive_daily_metrics(session_factory, trade_date, on_progress=None) -> dict`：
  - 股票清单来源 = `SELECT DISTINCT secucode FROM daily_kline WHERE ts <= trade_date`（只算已入库日K的股，**不依赖 TdxClient**，区别于 kline_archive）
  - 每股：取 `daily_kline` 该股 `trade_date` 及之前近 60 根 → `compute_indicators` → `score`/`signal_level`/四信号 → upsert `stock_metric`
  - 单股 try/except 隔离（坏股跳过，不影响其余），仿 screener/kline_archive
  - 返回 `{trade_date, total, ok, failed}`
- `archive_metrics_range(session_factory, start_date, end_date, on_progress=None) -> dict`：回填多日（循环 `archive_daily_metrics`，按日推进；返回 `{start, end, days, total, ok, failed}`）
- 进程内状态函数 `is_metrics_archive_running / get_metrics_archive_status / reset_metrics_archive_state`（同 kline_archive 模式）

## 调度 + 回填

- scheduler cron **16:15**（Asia/Shanghai）：`archive_daily_metrics(SessionLocal, _today_cst())` 增量当日。位于 `daily_kline_archive`(16:10) 之后，确保当日日K先入库。加 `is_metrics_archive_running` 互斥（与手动端点）。
- API（`api/archive.py`）：
  - `POST /api/archive/metrics?days=N`（202 后台跑；N∈{60, 250, all}，`all`=daily_kline 已有全部历史；返回 `task_id` + 日期范围）
  - `GET /api/archive/metrics/status`（仿 `/archive/daily/status`）
- 前端 ArchivePage 第四 Card「指标物化」：按钮（可选 days 范围）+ 进度轮询（复用既有 Card 模式）。
- 首次部署：按 `all` 回填 daily_kline 已有全部历史。预计算用现有 `compute_indicators`（Python 循环），5400 股 × 全历史首次预计几分钟~十几分钟（盘后跑、有进度，可接受）。

## screener 改造（`api/screener.py`）

- `latest = SELECT MAX(trade_date) FROM stock_metric`；若 None（从未预计算）→ 返回空 list + log。
- `rows = SELECT stock_metric.*, stock_meta.name FROM stock_metric WHERE trade_date = latest JOIN stock_meta`。
- 每行：`score`/`signal_level`/`macd_signal`/`kdj_signal`/`wr_signal`/`rsi_signal` 已物化直接用；`evaluate_extras` 用物化字段组装 ind dict 跑（O(1) 谓词）。
- signal 过滤 + `evaluate_extras` + sort（同阶段1 逻辑，数据源换表）。
- **删除**阶段1 的 `WHERE ts>=now-120d` daily_kline 全表查询与 compute loop（实时算路径下线）。

## 副图改造（`api/stocks.py` 的 `GET /{secucode}/indicators`）

- 优先查 `stock_metric WHERE secucode=? ORDER BY trade_date DESC LIMIT count`，reverse 升序，映射成 `{date, close, dif, dea, hist, k, d, j, wr, rsi}` 时序。
- **容错**：若该股 `stock_metric` 行数 < count → 回退实时算（读 `daily_kline` → `compute_indicators` → `indicator_series`），保证副图总有数据。
- 响应字段与阶段1 一致（前端 `IndicatorCharts` 不变）。

## 测试策略

- `tests/test_metric_archive.py`：直接 seed `daily_kline`（不依赖 tdx），验单日 `archive_daily_metrics` upsert 正确性 + 回填 `archive_metrics_range` + 进度状态 + 单股失败隔离。
- `tests/test_api_screener.py`：改为 seed `stock_metric`，验查表筛选（signal + extras + sort）；新增"表空返回空"用例。
- `tests/test_api_stocks.py` indicators：seed `stock_metric` 验副图查表 + 行数不足回退实时算用例。
- migration：alembic 0008 新建 `stock_metric`（conftest 的 TRUNCATE cascade 覆盖）。
- 现有 `test_indicator.py` 不动（纯函数不变）。

## 关键决策（已与用户确认）

1. **scope = 彻底**：screener + 副图都查 `stock_metric`（物化历史时序）。
2. `stock_metric` 字段 = `compute_indicators` 全快照 + 派生信号。
3. 预计算 16:15 cron 增量 + 手动按钮（days=60/250/all）。
4. 回填默认 `all`（daily_kline 已有全部历史，一次到位）。
5. 副图 `stock_metric` 不足 → 回退实时算（保证图完整）。
6. screener 表空 → 返回空 list（不崩）。

## 交付清单

1. `models/stock_metric.py` + alembic migration 0008（新建表 + 索引）
2. `services/metric_archive.py`（`archive_daily_metrics` + `archive_metrics_range` + 状态函数）
3. `api/archive.py` 加 metrics 端点 + `scheduler.py` 加 16:15 cron
4. `api/screener.py` 改查 `stock_metric`（删实时算路径）
5. `api/stocks.py` indicators 改查 `stock_metric` + 不足回退
6. `frontend/src/api/archive.ts` + `pages/ArchivePage.tsx` 加指标物化 Card
7. 上述测试
