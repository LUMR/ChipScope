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
│              （实时行情 3s / 日终 16:00）                │
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

- **定时任务已内嵌**：盘中每 3s 读 `watchlist` 表拉实时行情 → Redis；每交易日 16:00（Asia/Shanghai）采集股东 + 资金流。无需另起进程。
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
│   │   │   ├── ingest.py / realtime.py
│   │   │   └── ...
│   │   └── utils/
│   ├── alembic/versions/   # 0001 init · 0002 holders+flow · 0003 chip_distribution · 0004 watchlist
│   ├── scripts/            # seed_demo / smoke_ingest / smoke_chip
│   └── tests/              # 55 测试，纯算法 + API + 采集器 + watchlist
├── frontend/
│   └── src/                # pages / components / api / hooks / types
├── docker-compose.yml      # db(PostgreSQL 15) + redis
└── astock-analysis-design.md
```

---

## 测试与脚本

```bash
# 后端测试（需 docker 里的 PG 在线，测试直连真实库做 TRUNCATE 隔离）
cd backend && .venv/Scripts/python -m pytest            # 55 passed

# 合成数据冒烟：验证筹码引擎端到端（不依赖外部数据源）
PYTHONPATH=. .venv/Scripts/python scripts/smoke_chip.py

# 真实采集冒烟：拉全市场列表 + 茅台近 30 日K
.venv/Scripts/python scripts/smoke_ingest.py

# 前端
cd frontend && npm run lint && npx vitest run
```

---

## 数据源

| 数据 | 源 | 备注 |
|------|----|------|
| 日 K / 实时五档 | 东方财富 HTTP / 通达信 mootdx | 当前日 K 采集实际走东财 |
| 十大流通股东 | 东方财富 `datacenter-web` | 衰减系数来源 |
| 资金流向 | 东方财富 `fflow` | |

东财接口有限流，`EastMoneyClient` 内置最小请求间隔 + tenacity 指数退避重试。

---

## 开发路线

参考设计文档第十一节，阶段化推进：

- **P0–P3（已完成）**：基础设施 / 数据采集 / 筹码引擎 / REST API + WebSocket
- **P4（已完成）**：前端 K 线 + 火焰图 + 指标面板 + 历史回放
- **自选股配置页 + UI 重设计（已完成）**：watchlist 表 + CRUD API + 全局 WS；前端 AppLayout（顶部导航 + 常驻自选栏）、自选管理页（dnd-kit 拖拽排序）、B 风格主题、轮询实时报价（现价 + 涨跌幅）。设计见 `docs/superpowers/specs/`，计划见 `docs/superpowers/plans/`
- **P5（待办）**：Docker 全栈部署、监控告警、真实采集验证、股东/资金流前端可视化

实现计划文档位于 [`docs/superpowers/plans/`](./docs/superpowers/plans/)。

---

## 已知限制

- **形态识别阈值待校准：** `/pattern` 的"单峰密集"判定基于峰值区占比阈值，在 400-bin 真实分布下灵敏度不足，生产数据上可能漏判，需结合真实行情调参。
- **前端实时行情：** 走 WebSocket `/ws/realtime` 推送（scheduler 嵌入同进程后启用；曾因 scheduler/uvicorn 跨进程临时改轮询，单进程合并后已切回 WS）。连接建立后首条数据需等下一轮广播（≤3s），首屏首渲由 `GET /api/watchlist` 提供初始报价。
- **自选股单 scope：** watchlist 表预留 `scope` 字段，当前固定 `default`，未实现多用户/分组。
- **历史回填：** 衰减系数取最近一期季度数据，回填早期历史时存在已知近似。
- **数据源一致性：** 设计文档以通达信为日 K 主源，当前实现以东方财富为主，文档待同步。
