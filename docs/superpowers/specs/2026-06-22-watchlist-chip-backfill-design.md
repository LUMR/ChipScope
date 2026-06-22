# 自选股筹码补全 — 设计文档

> **日期：** 2026-06-22
> **目标：** 在「数据存档」页加一个按钮，一键对**所有自选股**重新拉取日K并**全量重算筹码分布**，自动补齐因停机/漏采而缺失的历史日期筹码。

---

## 1. 背景与关键机制

用户反馈：自选股的筹码分布图缺失了部分日期。

**筹码计算的真相（决定整个设计）：**
- `compute_chip_series`（`backend/app/services/chip_compute.py`）是**全量重算**——读该股 `daily_kline` 全部日K序列，逐日累加衰减，重新生成每一天的筹码分布。
- `upsert_chip_distribution` 用 `ON CONFLICT (secucode, ts) DO UPDATE` **幂等覆盖**。
- 因此筹码**不会单独缺某一天**。只要日K齐全 + 跑一次 `ingest_kline_and_chips`，该股全部历史日期的筹码一次性补齐。

**结论：**「自动补全缺失日期」在实现上 = **对自选股重新拉日K并全量重算筹码**，无法、也无需「只挑缺口日期补」。`scheduler.daily_kline_chip`（16:05）已在做这件事（`days=120`），本功能的增量价值是 **①即时手动触发（不必等 16:05）②可选更长的回填窗口（120/365/全部）**。

---

## 2. 范围决策（已与用户确认）

| 决策点 | 选择 |
|---|---|
| 补全范围 | **所有自选股批量补**（遍历 watchlist） |
| 回填窗口 | **UI 可选**：120 天 / 365 天 / 全部 |
| UI 位置 | **「数据存档」页加第二个 Card**（与「分时行情存档」同页） |

---

## 3. 方案选择

**选定方案 A：复刻分时存档模式，独立进程内状态。**

- 新建 `services/chip_backfill.py`（编排 + 独立状态 `_backfill_running`/`_backfill_status`），与 `services/minute_archive.py` 对称。
- 在 `api/archive.py` 加两个端点，复用其 fire-and-forget + 进程内状态 + 轮询模式。
- 两套状态独立，分时存档与筹码补全可并行互不阻塞。

**否决方案 B（泛化「通用后台任务」框架）：** YAGNI，当前仅两个任务，过度设计且需改造已上线的分时存档，回归风险高。
**否决方案 C（直接复用 `daily_kline_chip` 编排）：** `scheduler.py` 职责混淆，且 `daily_kline_chip` 无 `on_progress` 回调无法报进度。

---

## 4. 架构与组件

### 后端

| 文件 | 改动 | 职责 |
|---|---|---|
| `backend/app/services/chip_backfill.py`（新建） | `backfill_watchlist_chips(session_factory, tdx, em, days, on_progress)` + 进程内状态 get/set/is/reset（与 `minute_archive.py` 对称） | 编排：读 watchlist join stock_meta → 逐只 `ingest_kline_and_chips`，带进度回调 |
| `backend/app/api/archive.py`（扩展） | `POST /api/archive/chip-backfill` + `GET /api/archive/chip-backfill/status` + `_run_chip_backfill(days)` 后台任务 | fire-and-forget 触发 + 三态状态查询 |
| `backend/app/schemas/archive.py`（扩展） | `BackfillStatusOut`、`BackfillTriggerResponse` | Pydantic 响应模型 |

### 前端

| 文件 | 改动 |
|---|---|
| `frontend/src/pages/ArchivePage.tsx` | 加第二个 Card「自选股筹码补全」：`Select`(120/365/全部，默认 365) + 按钮 + `Progress` + total/ok/failed；独立 `backfillStatus` state + 独立 2s 轮询 |
| `frontend/src/api/archive.ts` | 加 `triggerChipBackfill(days)` + `getChipBackfillStatus()` |

### 关键常量与约定

- `ALL_DAYS = 1000`（`chip_backfill.py` 模块常量）：UI 选「全部」时传给 `tdx.daily_bars(count)`，约 3-4 年日K。mootdx `bars(offset=N)` 无硬上限，1000 足够。
- `parse_days(s: str) -> int`：服务层纯函数（`chip_backfill.py`）。`"all"`→`ALL_DAYS(1000)`、`"120"`→`120`、`"365"`→`365`、其他 → `ValueError`。端点层 `try/except ValueError` 返 422。`backfill_watchlist_chips` 接收**已解析的 int**。
- 编排**复用单 session + 单 em + 单 tdx**（与 `scheduler.daily_kline_chip` 一致，本质同一件事），逐只 `try/except` 计 `failed` 不中断。
- **不新增配置项**——窗口由 UI 选。

---

## 5. 数据流

```
[ArchivePage]  选窗口(120/365/all) → 点「开始补全」
     │ POST /api/archive/chip-backfill?days=365
     ▼
[archive.py] is_backfill_running()? ──是──► 409
     │否  _run_chip_backfill(365) 后台 task；立即 202 + {task_id, window}
     ▼
[chip_backfill.py] _backfill_status = running
     │ 开 tdx + em + session；读 watchlist join stock_meta
     │ for 每只自选股 (i/total):
     │   ingest_kline_and_chips(tdx,em,session,sec,secid,days=365)
     │     └─ daily_bars(365) → upsert 日K → 全量重算筹码 → ON CONFLICT 覆盖
     │   ok+=1 / except: failed+=1
     │   on_progress(i, total, ok, failed) → 更新 _backfill_status(running)
     ▼ 完成 / 异常
   _backfill_status = done{total,ok,failed} / error{error}
     ▲
[ArchivePage] 每 2s GET chip-backfill/status → 刷新 Progress
```

后台任务跑在 uvicorn 事件循环里（单进程模式，与分时存档同），API 进程内状态即可，**不用 Redis**。

---

## 6. API 契约

### `POST /api/archive/chip-backfill?days=<120|365|all>`

| 状态码 | 响应 | 条件 |
|---|---|---|
| 202 | `BackfillTriggerResponse{task_id, window}` | 成功调度后台任务 |
| 409 | `{"detail":"chip backfill already running"}` | `is_backfill_running()` 为真 |
| 422 | `{"detail":"invalid days, expected 120/365/all"}` | `days` 非合法值 |

- `task_id`：启动时间戳字符串（`str(int(time.time()))`），供前端参考。
- `window`：回传 `days` 原值（`"120"`/`"365"`/`"all"`）。

### `GET /api/archive/chip-backfill/status`

返回 `BackfillStatusOut | null`（从未触发过返回 null）。

**`BackfillStatusOut` 字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `state` | `"running"`/`"done"`/`"error"` | 任务状态 |
| `window` | `str` | `"120"`/`"365"`/`"all"` |
| `total` | `int` | 自选股总数 |
| `done` | `int` | 已处理（含 failed） |
| `ok` | `int` | 成功数 |
| `failed` | `int` | 失败数 |
| `started_at` | `int \| null` | 启动 unix 时间戳 |
| `finished_at` | `int \| null` | 完成 unix 时间戳 |
| `error` | `str \| null` | 整任务异常时的错误信息 |

**`BackfillTriggerResponse` 字段：** `task_id: str`、`window: str`。

---

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| `is_backfill_running()` 为真时再触发 | `409` |
| `days` 非 `120`/`365`/`all` | `422 invalid days` |
| watchlist 为空 | 后台任务直接 `done{total:0,ok:0,failed:0}`（正常完成，非错误） |
| 单只 `ingest_kline_and_chips` 正常返回（含 `{klines:0,chips:0}` 新股/停牌） | 计 `ok`（处理成功，无数据非失败） |
| 单只抛异常（tdx 拉取失败等） | `failed+=1`，`try/except` 不中断后续 |
| 东财限流（`resolve_float_shares` 失败） | 容错返回 `0` → `turnover=0` → 不衰减累积，**仍出图**（现有约束，非回归） |
| 整个后台任务异常 | `_backfill_status = error{error:str}`，`finally` 里 `set_backfill_running(False)` |
| backfill 与 16:05 `daily_kline_chip` 撞同一只 | 各自独立 `TdxClient`；`ingest` 全程 `ON CONFLICT` 幂等，并发安全 |

---

## 8. 测试（TDD，独立 `chipscope_test` 库）

**`backend/tests/test_chip_backfill.py`（新建）**
- `backfill_watchlist_chips` 主流程：fake tdx/em，watchlist 2 只，第 2 只 `ingest` 抛错 → 返回 `{total:2,ok:1,failed:1}`，`on_progress` 末次为 `(2,2,1,1)`。
- `days` 解析：`"all"→1000`、`"120"→120`、`"365"→365`、非法值 → `ValueError`。
- 进程内状态 `get/set/is/reset`。

**`backend/tests/test_api_archive.py`（扩展）**
- `POST /chip-backfill?days=365` → `202` 且后台任务被调度。
- 运行中再触发 → `409`。
- `days=999` → `422`。
- `GET /chip-backfill/status` 返回当前 `BackfillStatusOut`。

**前端：** `ArchivePage` 渲染第二个 Card（vitest，可选）。

---

## 9. 边界 / 已知约束

- mootdx 日K不复权，除权日跳变（现有约束，非新引入）。
- `ALL_DAYS=1000` 实际可拉根数取决于 mootdx 服务器（通常 ~800，约 3-4 年）。
- 全量重算每只跑其全部历史日K——自选股多 + 历史长时单次任务可能数分钟，但有实时进度，可接受。
- 东财限流导致 `float_shares=0` → 筹码退化为不衰减累积（与 `daily_kline_chip` 同）。

---

## 10. 不做（YAGNI）

- 不做「缺口日期检测/预览」——全量重算幂等，检测无意义。
- 不抽象通用后台任务框架。
- 不新增配置项（窗口由 UI 选，`ALL_DAYS` 为常量）。
- 不做单只股票补全按钮（本次范围仅批量）。
