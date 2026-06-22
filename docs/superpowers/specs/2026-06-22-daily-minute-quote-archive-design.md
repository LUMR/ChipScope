# 每日全市场分时行情存档（Daily Minute-Quote Archive）

- 日期：2026-06-22
- 状态：已通过设计评审，待实现
- 关联：复用现有 `TdxClient`(mootdx)、`scheduler.py`、`stock_meta`、Redis、前端 Header

## 1. 背景与目标

当前系统只把**日 K 线**落库（`daily_kline`），**实时行情只写 Redis、10s 过期、不落库**。用户需要一个"每日全量、精确到分钟"的行情存档能力，用于日后分时回放与分析。

目标：每个交易日收盘后，把**全市场沪深 A 股**当天的**分时数据**（每只股票 1 条记录，内含约 240 个分钟点）批量落库；提供前端按钮手动触发（异步执行 + 进度可见），并支持每日定时自动触发。

## 2. 已确认的需求决策

| 维度 | 决策 |
|---|---|
| 数据形态 | **当天分时图数据**（非 1 分钟 K 线、非盘中实时快照） |
| 采集范围 | **全市场沪深 A 股**（约 5000 只，通过 mootdx `stocks()` 刷新清单） |
| 触发方式 | **按钮手动触发（异步后台 + 进度）+ 每日定时 cron**，两入口共用同一采集函数 |
| 存储结构 | **JSONB**（每只每天 1 行，紧凑；与现有 `chip` 表风格一致） |
| 进度机制 | **Redis 状态 + 前端轮询 GET status** |
| 前端入口 | **Header「数据存档」**（全局操作，不放单股详情页） |

## 3. 数据模型

新增表 `minute_quote`：

| 列 | 类型 | 说明 |
|---|---|---|
| `trade_date` | `Date` | 交易日（PK） |
| `secucode` | `String(12)` | 外键 `stock_meta.secucode`（PK） |
| `data` | `JSONB` | 分时点序列，见下 |
| `updated_at` | `TIMESTAMPTZ` | `server_default=now()` + `onupdate=now()` |

主键 `(trade_date, secucode)`，保证幂等 upsert（同交易日重跑覆盖）。

`data` JSONB 结构：分钟点数组，每点 5 字段：

```json
[
  {"t": "09:31", "price": 38.12, "avg": 38.10, "vol": 12300, "amount": 468900.0},
  {"t": "09:32", "price": 38.20, "avg": 38.15, "vol": 9800,  "amount": 374400.0}
]
```

- `t`：`HH:MM`，交易时段内每分钟一个点（约 240 点/天）
- `price`：该分钟成交价（最新价）
- `avg`：当日截至该分钟的累计均价
- `vol`：**该分钟增量成交量（手）**
- `amount`：**该分钟增量成交额（元）**

> **实现期统一语义**：mootdx `minute_time_data` 返回的 volume/amount 若为累计值，解析时须做相邻点差分，统一存为"该分钟增量"。

迁移：`alembic revision --autogenerate -m "add minute_quote table"`。

## 4. 采集流程

新增模块 `backend/app/services/minute_archive.py`，按项目"采集与解析分离、纯函数可测"的约定组织。

### 4.1 刷新全市场清单

`refresh_stock_universe(tdx) -> int`：
- 调 `mootdx stocks(market=0)`（深）+ `stocks(market=1)`（沪）取全市场股票
- 仅保留沪深 A 股（过滤指数/债券/基金/ETF 等，复用 `api/stocks.py` 的 SecurityType 过滤思路）
- upsert 到 `stock_meta`（含 secucode/code/name/market/secid），返回条数

> `stock_meta` 当前只含已采集过的股票，不全；此步是"全量"的前提。

### 4.2 单只分时拉取与解析

`TdxClient.minute_time(symbol, date=None) -> list[dict]`（新增方法）：
- `date=None` → mootdx `minute_time_data(symbol)`（当天分时）
- `date="YYYYMMDD"` → mootdx `history_minute_time_data(symbol, date)`（指定历史日，仅最近若干天可取）
- 走线程池 `run_in_executor`（与现有 `quotes`/`daily_bars` 一致）
- 解析 DataFrame → `data` JSONB 点序列（含 4.1 节语义统一）

### 4.3 主采集函数

`archive_minute_quotes(trade_date, on_progress=None) -> dict`：
1. `refresh_stock_universe()` 刷新清单
2. 读取全部沪深 A 股 secucode 列表
3. 遍历：每只 `tdx.minute_time(code, date)` → 解析 → upsert `minute_quote`（`ON CONFLICT (trade_date, secucode) DO UPDATE`）
4. 单只失败 try/except 计入 `failed`、跳过、不影响其他
5. 每完成 N 只（如 50）调一次 `on_progress(done, total, failed)`
6. 返回 `{trade_date, total, ok, failed}`

- 全程复用一个 `TdxClient` 连接，`finally close()`
- upsert 复用 `ingest.py` 的 `insert(...).on_conflict_do_update(...)` 模式

## 5. 触发

两入口共用 `archive_minute_quotes()`。

### 5.1 API（按钮）

新增路由 `backend/app/api/archive.py`，prefix `/api/archive`：

- `POST /api/archive/minute?date=YYYY-MM-DD`
  - `date` 可选，默认当天（`utils/time.py` 交易日）
  - fire-and-forget 后台 task（复用 `_schedule_ingest` 模式），立即返回 `202 + {task_id}`
  - 已有任务在跑 → 返回 `409 {detail: "archive task already running"}`
- `GET /api/archive/minute/status`
  - 返回当前/最近一次任务状态（见第 6 节）

### 5.2 cron

`scheduler.py` 新增 job，`CronTrigger(hour=15, minute=30, timezone="Asia/Shanghai")`，`id="daily_minute_archive"`，调 `archive_minute_quotes(当天)`。

> 选 15:30（收盘后、`daily` 16:00 holders/flow 任务之前），错开既有任务。

## 6. 进度与状态

状态存 Redis（复用现有 `redis_url`），key `archive:minute:status`，TTL 24h：

```json
{
  "state": "running | done | error",
  "trade_date": "2026-06-22",
  "total": 5000,
  "done": 3120,
  "failed": 3,
  "started_at": 1719000000,
  "finished_at": 1719000600,
  "error": null
}
```

- 任务启动写 `running`，采集函数通过 `on_progress` 回调更新 `done/failed`，结束写 `done`/`error`
- 防重入：启动前 `GET` 状态，`state==running` 即拒绝（见 5.1 的 409）
- 前端轮询 `GET status`（间隔 2s）渲染进度条

## 7. 前端

Header 增「数据存档」入口（下拉或小面板）：
- 「存档今日分时」按钮 → `POST /api/archive/minute`
- 日期选择器（可选，补历史最近几天）→ `POST /api/archive/minute?date=`
- 进度条 + 状态文案（轮询 `GET status`，`done/total`、`failed` 计数、`state`）
- 复用 `api/client.ts:apiGet/apiPost` 与现有 Header 视觉风格

## 8. 错误处理

- 幂等：同 `trade_date` 重跑覆盖、行数不变
- 单只失败：try/except 计入 `failed`、日志、继续
- 任务防重入：Redis 状态锁 → 409
- 连接泄漏：`TdxClient` 全程 `try/finally close()`
- mootdx 限流/断连：复用现有 `TdxClient` 行为，单只失败不影响整体

## 9. 测试

真实 PostgreSQL（复用 `conftest.py`，TRUNCATE 隔离；mock 网络与 mootdx）：

- **解析**：mock `TdxClient.minute_time` 返回假 DataFrame → 验证 JSONB 点序列正确（含累计→增量差分）
- **幂等**：同 `trade_date` 跑两次，行数与内容不变
- **清单刷新**：mock `stocks()` 返回固定列表 → 验证仅 A 股 upsert 入 `stock_meta`
- **主流程**：mock 全链路，验证 `archive_minute_quotes` 返回 `{total, ok, failed}` 与 `on_progress` 回调
- **API**：`POST` 触发后 `GET status` 返回 running；任务在跑时 `POST` 返回 409
- **单只失败**：mock 中途一只抛错 → 该只计入 failed、其余仍 upsert

## 10. 实现期需验证的风险点

1. **mootdx 方法签名**：`minute_time_data` / `history_minute_time_data` / `stocks` 是否需显式 `market=` 参数、字段名是否与本文一致。现有 `TdxClient` 用裸 code 调 `quotes`/`bars` 已证明本环境自动识别市场，故大概率一致；实现首步用真实连接打一发确认。
2. **volume/amount 语义**：确认是累计还是增量，按第 3 节统一为增量。
3. **`history_minute_time_data` 可回溯天数**：通达信服务器通常仅保留最近若干天；补历史仅支持该窗口内，超出则 failed 计入并日志。

## 11. 不在范围内（YAGNI）

- 盘中实时快照、1 分钟 K 线、tick 级成交（本设计仅"当天分时图"存档）
- 分钟级数据的复杂时序查询/聚合接口（先存档；查询接口按后续需求再加）
- 多任务并发存档（同一时间只允许一个存档任务，409 防重入）
- WebSocket 推进度（轮询足够）
