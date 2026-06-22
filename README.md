# ChipScope — A 股股价与筹码分布分析系统

> 持续采集 A 股个股的**股价历史**与**筹码分布变更历史**，提供可视化分析界面。
>
> 后端基于 FastAPI + SQLAlchemy 2.0(async) + PostgreSQL；前端基于 React + ECharts。
> 详细设计见 [`astock-analysis-design.md`](./astock-analysis-design.md)。

---

## 核心功能

| 模块 | 说明 | 状态 |
|------|------|------|
| 日 K 线采集 | 开高低收/量/额/换手率/VWAP，东方财富 HTTP 接口 | ✅ |
| 筹码分布引擎 | 三角形分布 + 衰减叠加（NumPy 向量化），日终快照落库 | ✅ |
| 衍生指标 | 获利盘比例 / 平均成本 / 90% 集中度 / 筹码峰 | ✅ |
| 形态识别 | 单峰密集 / 高低位单峰 / 筹码发散 / 上下移 | ✅ |
| 十大流通股东 | 季度数据，计算衰减系数 A=1/(1−top10%) | ✅ |
| 资金流向 | 主力 / 超大 / 大 / 中 / 小单净额 | ✅ |
| 实时行情 | 通达信(mootdx) 五档盘口 → Redis 缓存 + WebSocket 推送；前端实时展示现价/涨跌幅 | ✅ |
| 自选股管理 | 网页配置自选股（搜索添加 / 拖拽排序 / 删除），联动 scheduler 监控 | ✅ |
| 分时存档 | 每交易日全市场沪深 A 股当天分时数据落库（~240 分钟点/股），前端按钮手动触发 + 每日 15:30 自动触发 | ✅ |
| 自选股筹码补全 | 一键对所有自选股全量重算筹码，补齐停机/漏采缺失的历史日期（按钮手动触发，可选 120/365/全部窗口） | ✅ |
| 可视化 | K 线图 + 筹码火焰图 + 指标面板 + 历史回放滑块（B 风格 UI） | ✅ |

---

## 技术栈

**后端：** FastAPI · SQLAlchemy 2.0 (asyncpg) · Alembic · APScheduler · httpx · tenacity · redis · NumPy · mootdx
**存储：** PostgreSQL 15 · Redis 7
**前端：** React 19 · TypeScript · Vite · ECharts（echarts-for-react）· Ant Design · react-router · dnd-kit

---

## 架构

```
┌─────────────────────────────────────────────────────┐
│              前端 React + ECharts                      │
│      K 线图 · 筹码火焰图 · 指标面板 · 历史回放          │
│  dev: vite :5173   /   省事: 由 :8001 静态托管          │
├─────────────────────────────────────────────────────┤
│            FastAPI (:8001) —— 单进程                    │
│   REST API · WebSocket · 内嵌 APScheduler 定时调度      │
│              （实时 3s / 15:30 分时 / 16:00 股东资金流）  │
├──────────────┬──────────────┬────────────────────────┤
│  数据采集引擎  │  筹码计算引擎  │      实时行情缓存        │
│  东财 httpx   │   NumPy      │   mootdx → Redis        │
│  通达信 mootdx│              │                        │
├──────────────┴──────────────┴────────────────────────┤
│                 PostgreSQL  ·  Redis                    │
│   K线时序表 · 筹码快照 JSONB · 股东表 · 资金流          │
└─────────────────────────────────────────────────────┘
```

---

## 快速开始

### 前置依赖

- Python ≥ 3.11
- Node.js ≥ 18
- Docker（用于起 PostgreSQL + Redis）

### 1. 启动数据库与缓存

```bash
docker compose up -d db redis
# db    → localhost:5433  (PG 容器内 5432)
# redis → localhost:6380  (Redis 容器内 6379)
```

> 主机端口刻意映射到 5433 / 6380，避免与本机已存在的 PG/Redis 冲突。

### 2. 配置后端环境

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows；Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

创建 `backend/.env`（已 gitignore，端口须与 docker 映射一致）：

```ini
CHIPSCOPE_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/chipscope
CHIPSCOPE_REDIS_URL=redis://localhost:6380/0
```

### 3. 初始化数据库（建表）

```bash
.venv/Scripts/alembic upgrade head
```

### 4. 构建前端（单端口模式需要；纯开发模式可跳过）

```bash
cd frontend
npm install
npm run build                   # 产物 frontend/dist，供后端 :8001 静态托管
```

### 5. 一条命令启动（API + 定时任务 + 前端，单进程 :8001）

```bash
cd backend
.venv/Scripts/uvicorn app.main:app --port 8001 --reload
```

- **定时任务已内嵌**（Asia/Shanghai）：盘中每 3s 读 `watchlist` 表拉实时行情 → Redis；**15:30 全市场分时存档**（mootdx）；16:00 采集股东 + 资金流（东财）；16:05 自选股增量日 K + 重算筹码（mootdx）。无需另起进程。
- 首次启动若 `watchlist` 表为空，用 `CHIPSCOPE_WATCHLIST_DEFAULT` 种子初始化（仅插入已存在于 stock_meta 的）。
- **前端由 :8001 静态托管**：访问 http://localhost:8001 即是完整应用；API 文档 http://localhost:8001/docs。
- 若不想在 API 进程里跑调度（如生产分离部署），设 `CHIPSCOPE_SCHEDULER_ENABLED=false`，再单独 `.venv/Scripts/python -m app.scheduler`。

> **端口约定：** 后端固定跑在 **8001**。

### 6.（可选）开发模式：前端热更新

频繁改前端、需要 HMR 时，额外开一个终端（后端仍跑第 5 步的 uvicorn）：

```bash
cd frontend
npm run dev                     # http://localhost:5173
```

vite dev server 会把 `/api`、`/ws` 反向代理到 `http://localhost:8001`，改前端无需重新 build。

### 7. 灌入示例数据（可选，便于直接看效果）

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python scripts/seed_demo.py
# 写入 600519.SH 的 90 天合成日K + 筹码分布，供前端可视化
```

---

## 配置项

所有配置通过环境变量注入（前缀 `CHIPSCOPE_`），定义见 [`backend/app/config.py`](./backend/app/config.py)。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CHIPSCOPE_DATABASE_URL` | `...localhost:5432/chipscope` | PostgreSQL async 连接串 |
| `CHIPSCOPE_REDIS_URL` | `redis://localhost:6379/0` | Redis 连接串 |
| `CHIPSCOPE_EASTMONEY_MIN_INTERVAL` | `0.5` | 东财两次请求最小间隔（秒），防限流 |
| `CHIPSCOPE_EASTMONEY_USER_AGENT` | Chrome UA | 东财请求头 |
| `CHIPSCOPE_WATCHLIST_DEFAULT` | `600519.SH,000001.SZ,000858.SZ,601318.SH,002594.SZ` | watchlist 表为空时首次 seed 的自选股（逗号分隔 secucode，全格式） |
| `CHIPSCOPE_SCHEDULER_ENABLED` | `true` | 是否在 uvicorn 进程内嵌入定时任务；`false` 时需另起 `python -m app.scheduler` |
| `CHIPSCOPE_FRONTEND_DIST` | `<项目根>/frontend/dist` | 前端构建产物目录；指向含 index.html 的目录即启用 :8001 静态托管，否则退化为纯 API |
| `CHIPSCOPE_KLINE_HISTORY_DAYS` | `120` | 加自选时首次拉取的日 K 天数；daily 任务无数据兜底天数 |
| `CHIPSCOPE_CHIP_DECAY_DEFAULT` | `2.0` | 无股东数据（新股/未跑 daily）时的筹码衰减系数兜底 |

---

## REST / WebSocket API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/stocks?q=` | 股票列表，按代码/名称模糊搜索 |
| GET | `/api/stocks/{secucode}/kline` | 日 K 线（支持 start/end/limit） |
| GET | `/api/stocks/{secucode}/chips?date=` | 筹码分布（指定日或最新） |
| GET | `/api/stocks/{secucode}/chips/history` | 筹码指标历史序列 |
| GET | `/api/stocks/{secucode}/holders` | 十大流通股东 |
| GET | `/api/stocks/{secucode}/flow` | 资金流向 |
| GET | `/api/stocks/{secucode}/pattern` | 筹码形态识别结果 |
| GET | `/api/watchlist` | 自选股列表（含名称/行业/实时现价/涨跌幅） |
| POST | `/api/watchlist` | 添加自选（body `{secucode}`，幂等） |
| DELETE | `/api/watchlist/{secucode}` | 移出自选 |
| PUT | `/api/watchlist/reorder` | 拖拽排序（body `{secucodes:[...]}`） |
| POST | `/api/archive/minute?date=` | 触发全市场分时存档（异步后台，202；运行中 409；非法日期 422） |
| GET | `/api/archive/minute/status` | 存档任务状态（state/total/done/ok/failed），前端轮询进度 |
| POST | `/api/archive/chip-backfill?days=` | 触发自选股筹码补全（异步后台，202；运行中 409；非法窗口 422） |
| GET | `/api/archive/chip-backfill/status` | 补全任务状态（state/window/total/done/ok/failed），前端轮询进度 |
| WS  | `/ws/realtime/{code}` | 单股实时行情订阅（code 为裸代码） |
| WS  | `/ws/realtime` | 全局实时行情订阅（所有自选股） |

`secucode` 形如 `600519.SH` / `000001.SZ`。

> **前端实时行情走 WebSocket** `/ws/realtime`（全局订阅）：scheduler 嵌入 uvicorn 同进程，`broadcast_global` 每 3s 直达前端。`GET /api/watchlist` 仍返回带报价的自选股列表，供首屏首渲。

---

## 筹码分布算法

```
当日分布 = 当日新增成本分布 × effective_turnover  +  昨日分布 × (1 − effective_turnover)
effective_turnover = min(换手率 × 衰减系数 / 100, 0.95)     # 截断防负权重
衰减系数 A = 1 / (1 − 前十大流通股东累计占比)
```

- **当日成本分布**：以 VWAP 为峰、`[最低价, 最高价]` 为底的三角形，按成交量归一化。
- **价格分箱**：固定 400 个 bin 覆盖 `[序列最低价×0.9, 序列最高价×1.1]`。
- **衍生指标**：获利盘比例、平均成本、90% 集中度 `(上沿−下沿)/(上沿+下沿)×2`、筹码峰。

核心实现：[`backend/app/services/chip_engine.py`](./backend/app/services/chip_engine.py)（纯函数，无副作用）、[`chip_metrics.py`](./backend/app/services/chip_metrics.py)、[`chip_pattern.py`](./backend/app/services/chip_pattern.py)。

---

## 项目结构

```
chipscope/
├── backend/
│   ├── app/
│   │   ├── main.py / config.py / database.py / scheduler.py
│   │   ├── api/            # 路由: stocks / chips / websocket
│   │   ├── models/         # SQLAlchemy 模型
│   │   ├── schemas/        # Pydantic 响应模型
│   │   ├── services/
│   │   │   ├── chip_engine.py / chip_metrics.py / chip_pattern.py / chip_compute.py
│   │   │   ├── collector/  # eastmoney / tdx_client / retry
│   │   │   ├── ingest.py / realtime.py / kline_chip.py / minute_archive.py
│   │   │   └── ...
│   │   └── utils/
│   ├── alembic/versions/   # 0001 init · 0002 holders+flow · 0003 chip_distribution · 0004 watchlist · 0005 float_shares · 0006 minute_quote
│   ├── scripts/            # seed_demo / smoke_ingest / smoke_chip / smoke_minute_archive
│   └── tests/              # 97 测试，纯算法 + API + 采集器 + watchlist + archive
├── frontend/
│   └── src/                # pages / components / api / hooks / types
├── docker-compose.yml      # db(PostgreSQL 15) + redis
└── astock-analysis-design.md
```

---

## 测试与脚本

```bash
# 后端测试（独立测试库 chipscope_test，每用例 TRUNCATE 隔离；mock HTTP/TCP，不 mock DB）
cd backend && .venv/Scripts/python -m pytest            # 97 passed

# 合成数据冒烟：验证筹码引擎端到端（不依赖外部数据源）
PYTHONPATH=. .venv/Scripts/python scripts/smoke_chip.py

# 真实采集冒烟：拉全市场列表 + 茅台近 30 日K
.venv/Scripts/python scripts/smoke_ingest.py

# 分时存档冒烟：刷新全市场清单 → 前 N 只真实采分时落库（验证 mootdx minute 全链路）
PYTHONPATH=. .venv/Scripts/python scripts/smoke_minute_archive.py 5

# 前端
cd frontend && npm run lint && npx vitest run
```

---

## 数据源

| 数据 | 源 | 备注 |
|------|----|------|
| 日 K / 实时五档 / 分时 / 股票清单 | 通达信 mootdx（TCP） | K 线主源已切 mootdx 绕过东财反爬；日 K 不复权 |
| 分时存档 | 通达信 mootdx `minute`/`minutes` | 当天 + 最近若干交易日；仅提供价格/成交量，无均价/成交额 |
| 十大流通股东 / 资金流向 / 股票搜索 | 东方财富 HTTP | 衰减系数来源；搜索过滤仅沪深 A 股 |

东财接口有限流，`EastMoneyClient` 内置最小请求间隔 + tenacity 指数退避重试；mootdx 首次需 `python -m mootdx bestip` 探测最优服务器。

---

## 开发路线

参考设计文档第十一节，阶段化推进：

- **P0–P3（已完成）**：基础设施 / 数据采集 / 筹码引擎 / REST API + WebSocket
- **P4（已完成）**：前端 K 线 + 火焰图 + 指标面板 + 历史回放
- **自选股配置页 + UI 重设计（已完成）**：watchlist 表 + CRUD API + 全局 WS；前端 AppLayout（顶部导航 + 常驻自选栏）、自选管理页（dnd-kit 拖拽排序）、B 风格主题、WebSocket 实时报价（现价 + 涨跌幅）。设计见 `docs/superpowers/specs/`，计划见 `docs/superpowers/plans/`
- **每日全市场分时存档（已完成）**：`minute_quote` 表（JSONB 分时点）+ mootdx `minute`/`minutes` 采集 + A 股前缀过滤；前端「数据存档」页按钮手动触发（异步 + 进度轮询）+ 每日 15:30 cron 自动。spec `docs/superpowers/specs/2026-06-22-daily-minute-quote-archive-design.md`，plan `docs/superpowers/plans/2026-06-22-daily-minute-quote-archive.md`
- **自选股筹码补全（已完成）**：数据存档页加按钮，一键对所有自选股全量重算筹码补齐缺失日期（窗口可选 120/365/全部）。复用 ingest_kline_and_chips 编排 + 存档页按钮/进度模式。spec `docs/superpowers/specs/2026-06-22-watchlist-chip-backfill-design.md`，plan `docs/superpowers/plans/2026-06-22-watchlist-chip-backfill.md`
- **P5（待办）**：Docker 全栈部署、监控告警、股东/资金流前端可视化

实现计划文档位于 [`docs/superpowers/plans/`](./docs/superpowers/plans/)。

---

## 已知限制

- **形态识别阈值待校准：** `/pattern` 的"单峰密集"判定基于峰值区占比阈值，在 400-bin 真实分布下灵敏度不足，生产数据上可能漏判，需结合真实行情调参。
- **前端实时行情：** 走 WebSocket `/ws/realtime` 推送（scheduler 嵌入同进程后启用；曾因 scheduler/uvicorn 跨进程临时改轮询，单进程合并后已切回 WS）。连接建立后首条数据需等下一轮广播（≤3s），首屏首渲由 `GET /api/watchlist` 提供初始报价。
- **自选股单 scope：** watchlist 表预留 `scope` 字段，当前固定 `default`，未实现多用户/分组。
- **历史回填：** 衰减系数取最近一期季度数据，回填早期历史时存在已知近似。
- **分时存档：** mootdx 分时接口仅提供价格 + 成交量，不含均价/成交额；`minutes` 仅能补最近若干交易日；日 K / 分时均不复权，除权日有跳变。
