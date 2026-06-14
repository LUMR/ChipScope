# ChipScope — A股股价与筹码分布分析系统

> **版本:** v1.1  
> **日期:** 2026-06-14  
> **状态:** 设计阶段  
> **变更:** v1.1 — 数据源改用通达信(mootdx)为主，东财降为辅助源

---

## 一、系统概述

### 1.1 目标

构建一个 Web 服务，持续采集 A 股个股的**股价变更历史**和**筹码分布变更历史**，提供可视化分析界面。

### 1.2 核心功能

| 功能模块 | 说明 |
|----------|------|
| 股价历史采集 | 日K/周K/月K线数据，含开高低收量额换手率 |
| 实时行情推送 | 盘中实时价格、五档盘口 |
| 筹码分布计算 | 每日收盘后自动计算，存储历史快照 |
| 筹码可视化 | 横向火焰图（价格 vs 持仓量），支持历史回放 |
| 股东数据跟踪 | 十大流通股东季度变化趋势 |
| 形态识别 | 单峰密集、筹码发散、震荡洗盘等经典形态自动标注 |

### 1.3 技术栈总览

```
┌─────────────────────────────────────────────────────┐
│                    前端 (React)                       │
│   ECharts/Lightweight-Charts · 筹码火焰图 · K线图      │
├─────────────────────────────────────────────────────┤
│                  API 网关 (FastAPI)                    │
│        REST API · WebSocket实时推送 · 认证              │
├──────────────┬──────────────┬────────────────────────┤
│  数据采集引擎  │ 筹码计算引擎  │   定时调度器 (APScheduler)│
│  (mootdx+    │  (NumPy)    │                        │
│   aiohttp)   │             │                        │
├──────────────┴──────────────┴────────────────────────┤
│              PostgreSQL + TimescaleDB                  │
│     K线时序表 · 筹码快照JSONB · 股东表 · 元数据         │
├─────────────────────────────────────────────────────┤
│                   Redis (缓存层)                       │
│         最新行情 · 计算结果缓存 · 任务队列               │
└─────────────────────────────────────────────────────┘
```

---

## 二、数据源方案

### 2.1 数据源选型

| 数据 | 主数据源 | 备用源 | 频率 |
|------|----------|--------|------|
| 历史日K/周K/月K | **通达信 `mootdx`** | 东方财富 `push2his` | 每日收盘后 |
| 实时行情+五档盘口 | **通达信 `mootdx`** | 腾讯 `qt.gtimg.cn` | 盘中3-5秒 |
| 分笔成交（可选） | **通达信 `mootdx`** | — | 盘中采集 |
| 资金流向 | 东方财富 `fflow` | — | 每日收盘后 |
| 十大流通股东 | 东方财富 `datacenter-web` | — | 季度 |
| 流通股本 | 东方财富实时行情字段 | F10接口 | 随股本变动 |

> **选型说明：** 通达信接口通过 `mootdx` 库直连通达信行情服务器（TCP二进制协议），
> 优势在于延迟极低、无频率限制、数据更全（含五档盘口和分笔数据）。
> 股东数据和资金流向仍走东方财富 HTTP API，因通达信不提供这些数据。

### 2.2 通达信核心接口（主数据源）

**连接与初始化：**
```python
from mootdx.quotes import Quotes

# 标准行情服务器（自动从上百台服务器中选最快）
client = Quotes.factory(market='std')

# 扩展行情服务器（用于深市或特殊品种）
# client = Quotes.factory(market='ext')
```

**历史K线：**
```python
# 日K线（frequency=9），前复权
df = client.bars(symbol='600519', frequency=9, offset=500)
# 返回 DataFrame: datetime, open, close, high, low, vol, amount

# frequency 映射:
#   0=5分钟, 1=15分钟, 2=30分钟, 3=60分钟
#   4=日线, 5=周线, 6=月线, 7=1分钟, 8=1分钟K
#   9=日K, 10=季K, 11=年K
# offset: 返回最近N根K线
```

**实时行情 + 五档盘口（一步到位）：**
```python
# 实时行情（含五档买卖盘）
quotes = client.quotes(symbol='600519')
# 返回: 今开/昨收/最高/最低/现价/总量/总额
#       五档买价买量、五档卖价卖量

# 批量查询（高效）
quotes = client.quotes(symbol=['600519', '000001', '002594'])
```

**分笔成交（可选，用于更精确的当日成本分布）：**
```python
ticks = client.transaction(symbol='600519', start=0, offset=100)
# 返回逐笔成交: 时间、价格、现手、买卖方向
# 可替代三角形分布法，实现更精确的当日筹码计算
```

**服务器管理与容错：**
```python
from mootdx.quotes import Quotes

# mootdx 内置IP列表，自动ping选最快服务器
# 如需手动指定或刷新IP列表：
# python -c "from mootdx.quotes import Quotes; Quotes.factory(market='std')"
```

### 2.3 东方财富辅助接口（股东/资金流）

> 通达信不提供股东数据和资金流向，这两类数据仍走东方财富。

**十大流通股东（衰减系数计算必需）：**
```
GET https://datacenter-web.eastmoney.com/api/data/v1/get
  ?reportName=RPT_F10_EH_FREEHOLDERS
  &filter=(SECUCODE="600519.SH")
  &columns=ALL
```

**资金流向：**
```
GET https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get
  ?secid=1.600519
  &lmt=120
```

**反爬注意：** 东财HTTP接口设置 `User-Agent`，请求间隔 ≥ 0.5秒。通达信TCP连接无此限制，但建议单连接 ≤ 5 req/s 以避免被断开。

---

## 三、数据库设计

### 3.1 PostgreSQL + TimescaleDB

```sql
-- ============ 1. 股票基础信息 ============
CREATE TABLE stock_meta (
    secucode    VARCHAR(12) PRIMARY KEY,   -- 600519.SH
    code        VARCHAR(8)  NOT NULL,      -- 600519
    name        VARCHAR(20) NOT NULL,      -- 贵州茅台
    market      VARCHAR(4)  NOT NULL,      -- SH / SZ / BJ
    secid       VARCHAR(12) NOT NULL,      -- 1.600519（东财格式）
    list_date   DATE,
    delist_date DATE,
    industry    VARCHAR(40),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============ 2. 日K线（TimescaleDB超表）============
CREATE TABLE daily_kline (
    ts              TIMESTAMPTZ NOT NULL,
    secucode        VARCHAR(12) NOT NULL,
    open            NUMERIC(10,3),
    close           NUMERIC(10,3),
    high            NUMERIC(10,3),
    low             NUMERIC(10,3),
    volume          BIGINT,         -- 成交量(手)
    amount          NUMERIC(18,2),  -- 成交额(元)
    turnover_rate   NUMERIC(8,4),   -- 换手率%
    pct_change      NUMERIC(8,4),   -- 涨跌幅%
    vwap            NUMERIC(10,3),  -- 均价 = amount/volume/100
    PRIMARY KEY (secucode, ts)
);
SELECT create_hypertable('daily_kline', 'ts');

-- ============ 3. 筹码分布快照（核心）============
CREATE TABLE chip_distribution (
    ts              TIMESTAMPTZ NOT NULL,
    secucode        VARCHAR(12) NOT NULL,
    distribution    JSONB NOT NULL,    -- {"15.00": 1200, "15.01": 3500, ...}
    decay_coeff     NUMERIC(6,2),      -- 当日使用的衰减系数
    concentration   NUMERIC(8,4),      -- 90%筹码集中度
    cost_high       NUMERIC(10,3),     -- 90%筹码上沿
    cost_low        NUMERIC(10,3),     -- 90%筹码下沿
    profit_ratio    NUMERIC(8,4),      -- 获利盘比例(收盘价)
    avg_cost        NUMERIC(10,3),     -- 平均持仓成本
    PRIMARY KEY (secucode, ts)
);
SELECT create_hypertable('chip_distribution', 'ts');

-- GIN索引：支持JSONB查询特定价位筹码
CREATE INDEX idx_chip_dist ON chip_distribution USING GIN (distribution);

-- ============ 4. 十大流通股东 ============
CREATE TABLE top_holders (
    ts              TIMESTAMPTZ NOT NULL,   -- 报告期
    secucode        VARCHAR(12) NOT NULL,
    rank            SMALLINT,
    holder_name     VARCHAR(100),
    hold_num        BIGINT,           -- 持股数
    hold_ratio      NUMERIC(8,4),     -- 占流通股比例%
    change_num      BIGINT,           -- 较上期变动
    holder_type     VARCHAR(20),      -- 基金/个人/机构
    PRIMARY KEY (secucode, ts, rank)
);

-- ============ 5. 股东汇总（衰减系数来源）============
CREATE TABLE holder_summary (
    ts              TIMESTAMPTZ NOT NULL,
    secucode        VARCHAR(12) NOT NULL,
    top10_ratio     NUMERIC(8,4),   -- 前十大流通股东累计占比%
    decay_coeff     NUMERIC(6,2),   -- 计算得出的衰减系数
    float_shares    BIGINT,         -- 流通股本
    PRIMARY KEY (secucode, ts)
);

-- ============ 6. 资金流向 ============
CREATE TABLE money_flow (
    ts              TIMESTAMPTZ NOT NULL,
    secucode        VARCHAR(12) NOT NULL,
    main_net        NUMERIC(18,2),  -- 主力净流入
    super_large_net NUMERIC(18,2),  -- 超大单
    large_net       NUMERIC(18,2),  -- 大单
    medium_net      NUMERIC(18,2),  -- 中单
    small_net       NUMERIC(18,2),  -- 小单
    PRIMARY KEY (secucode, ts)
);
SELECT create_hypertable('money_flow', 'ts');
```

### 3.2 存储估算

| 数据类型 | 单股单日大小 | 5000只股票×1年 | 说明 |
|----------|-------------|---------------|------|
| 日K线 | ~200B | ~250MB | 结构化，压缩后更小 |
| 筹码快照 | ~5-20KB (JSONB) | ~15-60GB | 主要存储开销 |
| 股东数据 | ~1KB | ~20MB | 季度更新 |
| 资金流向 | ~100B | ~130MB | 结构化 |

> 筹码快照是存储大户。可以考虑：只保留近2年精确快照，更早的降采样为周快照。

---

## 四、筹码分布计算引擎

### 4.1 核心算法

```
当日筹码分布 = 当日新增成本分布 × (换手率 × 衰减系数)
             + 昨日筹码分布 × (1 - 换手率 × 衰减系数)
```

### 4.2 衰减系数

```
衰减系数 A = 1 / (1 - 前十大流通股东累计占比)
```

| 前十大占比 | 衰减系数 | 说明 |
|-----------|---------|------|
| 50% | 2.0 | 中盘股常见 |
| 80% | 5.0 | 大盘股 |
| 90% | 10.0 | 高度控盘 |
| 95% | 20.0 | 极度控盘 |

### 4.3 当日成本分布（三角形分布法）

将当日成交量按以均价为峰顶的三角形分配到 [最低价, 最高价] 区间：

```
       均价
        /\
       /  \
      /    \
     /      \
  最低价   最高价

每个价格区间的筹码量 ∝ 三角形在该位置的纵坐标
```

> **进阶（可选）：** 如已采集通达信分笔成交数据，可直接按逐笔成交价格统计
> 当日真实成本分布，精度远高于三角形近似。分笔数据保留约7天（存储量大），
> 仅用于关键日期（如放量日、涨停日）的筹码精算。

### 4.4 衍生指标

| 指标 | 计算方式 |
|------|---------|
| 获利盘比例 | 当前价格以下的筹码量 / 总筹码量 |
| 平均成本 | Σ(价格 × 筹码量) / Σ(筹码量) |
| 90%筹码集中度 | (90%上沿 - 90%下沿) / (90%上沿 + 90%下沿) × 2 |
| 筹码峰位置 | 筹码量最大的价格区间 |

### 4.5 计算流程

```
每日15:30收盘后：
  1. 采集当日日K线数据（高/低/收/量/额/换手率）
  2. 获取最新衰减系数（从holder_summary表读取）
  3. 加载昨日筹码分布快照
  4. 计算当日VWAP = 成交额 / (成交量 × 100)
  5. 按三角形分布生成当日新增筹码
  6. 衰减旧筹码 + 叠加新筹码
  7. 计算衍生指标（获利盘/集中度/均成本）
  8. 存储当日快照到 chip_distribution 表
```

---

## 五、后端 API 设计

### 5.1 技术选型

- **框架：** FastAPI (异步、自动文档、WebSocket)
- **ORM：** SQLAlchemy 2.0 + asyncpg
- **调度：** APScheduler（定时采集+计算）
- **缓存：** Redis

### 5.2 REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stocks` | 股票列表（支持搜索/筛选） |
| GET | `/api/stocks/{code}/kline` | K线数据（支持日/周/月、时间范围） |
| GET | `/api/stocks/{code}/chips` | 筹码分布（支持指定日期） |
| GET | `/api/stocks/{code}/chips/history` | 筹码指标历史（获利盘/集中度趋势） |
| GET | `/api/stocks/{code}/holders` | 十大流通股东列表 |
| GET | `/api/stocks/{code}/flow` | 资金流向 |
| GET | `/api/stocks/{code}/pattern` | 筹码形态识别结果 |
| WS  | `/ws/realtime/{code}` | 实时行情推送 |

### 5.3 示例响应

**筹码分布：**
```json
{
  "code": "600519",
  "date": "2026-06-13",
  "current_price": 1685.00,
  "distribution": [
    {"price": 1600.00, "volume": 1200000, "ratio": 0.08},
    {"price": 1620.00, "volume": 2500000, "ratio": 0.17},
    {"price": 1650.00, "volume": 3800000, "ratio": 0.25},
    {"price": 1680.00, "volume": 3100000, "ratio": 0.21},
    {"price": 1700.00, "volume": 1800000, "ratio": 0.12}
  ],
  "metrics": {
    "profit_ratio": 0.72,
    "avg_cost": 1658.50,
    "concentration_90": 0.12,
    "cost_low_90": 1610.00,
    "cost_high_90": 1720.00,
    "peak_price": 1650.00
  },
  "pattern": {
    "name": "单峰密集",
    "confidence": 0.85,
    "description": "90%筹码集中在1610-1720区间，集中度12%"
  }
}
```

---

## 六、前端设计

### 6.1 技术选型

- **框架：** React 18 + TypeScript
- **图表库：** ECharts（K线+筹码火焰图）+ Lightweight-Charts（专业K线）
- **UI库：** Ant Design / Shadcn UI

### 6.2 核心页面

```
┌─────────────────────────────────────────────────────┐
│  顶部导航：搜索框 · 自选股 · 市场概览                    │
├──────────┬──────────────────────────────────────────┤
│          │  ┌──────────────────────────────────┐    │
│  左侧    │  │         K线图 + 均线              │    │
│  自选股  │  │                                  │    │
│  列表    │  ├──────────────────────────────────┤    │
│  ·茅台   │  │    筹码分布火焰图（横向）          │    │
│  ·平安   │  │    ▓▓▓▓▓▓▓░░░                  │    │
│  ·招商   │  │    ▓▓▓▓▓▓▓▓▓▓▓░░               │    │
│          │  │    ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓              │    │
│          │  │    ▓▓▓▓▓▓▓▓▓▓▓░░               │    │
│          │  │    ▓▓▓▓▓░░░░░                  │    │
│          │  │    ←低价     现价     高价→     │    │
│          │  ├──────────────────────────────────┤    │
│          │  │  指标面板：获利盘72% 集中度12%    │    │
│          │  │  形态：单峰密集(85%)              │    │
│          │  ├──────────────────────────────────┤    │
│          │  │  股东变化趋势 · 资金流向          │    │
│          └──────────────────────────────────┘    │
│                                                    │
│  日期滑块：◄━━━━●━━━━━━━━━━━► 2026-01-01 → 06-13  │
│  (拖动回放历史筹码变化)                               │
└─────────────────────────────────────────────────────┘
```

### 6.3 筹码火焰图

- **横轴：** 价格区间
- **纵轴：** 颜色深度表示筹码量（红多绿少）
- **交互：** 鼠标悬停显示该价位具体筹码量和占比
- **回放：** 底部日期滑块拖动，动态展示筹码迁移过程

---

## 七、采集调度

| 任务 | 频率 | 执行时间(北京) | 说明 |
|------|------|---------------|------|
| 全市场日K线增量 | 每交易日 | 15:45 | 收盘后15分钟 |
| 筹码分布计算 | 每交易日 | 16:00 | K线采集完成后 |
| 实时行情缓存 | 盘中 | 9:25-15:00 | 每3秒刷新（通达信五档盘口） |
| 分笔成交采集（可选） | 盘中 | 9:30-15:00 | 每30秒拉取增量分笔 |
| 十大流通股东 | 每季度 | 财报披露后T+1 | 更新衰减系数 |
| 历史数据回填 | 首次部署 | 一次性 | 采集近2年日K并计算筹码 |

### 首次部署回填流程

```
对每只股票：
  1. 采集近2年日K线数据（约480条）
  2. 采集最新一期十大流通股东数据 → 计算衰减系数
  3. 从最早日期开始逐日迭代计算筹码分布
  4. 存储每日快照
  5. 计算衍生指标
```

> 5000只股票 × 480天 ≈ 240万次迭代，单机约需2-4小时完成。

---

## 八、形态识别规则

| 形态 | 判定条件 | 市场含义 |
|------|---------|---------|
| 单峰密集 | 90%筹码集中度 < 15%，且峰值区筹码占比 > 40% | 变盘前夜，关注突破方向 |
| 双峰密集 | 存在两个明显筹码峰，峰间谷底 < 峰值50% | 上方有压力，下方有支撑 |
| 筹码发散 | 90%集中度 > 30%，筹码分散在各价位 | 上方套牢盘多，上涨阻力大 |
| 高位单峰 | 单峰密集 + 当前价格在峰位上方 > 5% | 低位筹码获利了结风险 |
| 低位单峰 | 单峰密集 + 当前价格在峰位下方 < 5% | 高位筹码割肉，可能见底 |
| 筹码下移 | 近30天平均成本持续下降 | 恐慌抛售，下方承接弱 |
| 筹码上移 | 近30天平均成本持续上升 | 资金持续进场吸筹 |

---

## 九、项目目录结构

```
chipscope/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── config.py            # 配置管理
│   │   ├── database.py          # 数据库连接
│   │   ├── models/              # SQLAlchemy 模型
│   │   │   ├── stock.py
│   │   │   ├── kline.py
│   │   │   ├── chip.py
│   │   │   └── holder.py
│   │   ├── api/                 # API 路由
│   │   │   ├── stocks.py
│   │   │   ├── chips.py
│   │   │   └── realtime.py
│   │   ├── services/            # 业务逻辑
│   │   │   ├── collector/       # 数据采集
│   │   │   │   ├── tdx_client.py   # 通达信(mootdx)：K线/实时/分笔
│   │   │   │   ├── eastmoney.py    # 东财：股东/资金流向
│   │   │   │   └── fallback.py     # 备用源切换(tencent/sina)
│   │   │   ├── chip_engine.py   # 筹码分布计算引擎
│   │   │   ├── pattern_recognizer.py  # 形态识别
│   │   │   └── scheduler.py     # 定时任务调度
│   │   └── utils/
│   ├── alembic/                 # 数据库迁移
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── KLineChart.tsx
│   │   │   ├── ChipFlame.tsx     # 筹码火焰图
│   │   │   ├── MetricPanel.tsx
│   │   │   └── DateSlider.tsx
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   └── StockDetail.tsx
│   │   └── api/                  # API 客户端
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml            # PG + Redis + Backend + Frontend
└── README.md
```

---

## 十、部署方案

### 10.1 Docker Compose（推荐）

```yaml
version: '3.8'
services:
  db:
    image: timescale/timescaledb:latest-pg15
    environment:
      POSTGRES_DB: chipscope
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  backend:
    build: ./backend
    depends_on: [db, redis]
    environment:
      DATABASE_URL: postgresql://postgres:***@db:5432/chipscope
      REDIS_URL: redis://redis:6379
    ports:
      - "8000:8000"

  frontend:
    build: ./frontend
    depends_on: [backend]
    ports:
      - "3000:3000"

volumes:
  pgdata:
```

### 10.2 最低配置

| 组件 | 最低配置 | 建议 |
|------|---------|------|
| CPU | 2核 | 4核+ |
| 内存 | 4GB | 8GB |
| 磁盘 | 50GB SSD | 100GB SSD |
| 网络 | 能访问通达信行情服务器(TCP 7709等) + 东财/新浪HTTP | — |

---

## 十一、开发计划

| 阶段 | 周期 | 交付物 |
|------|------|--------|
| P0: 基础设施 | 第1周 | Docker环境 + 数据库初始化 + 采集框架 |
| P1: 数据采集 | 第2-3周 | 日K线采集 + 股东数据采集 + 历史回填 |
| P2: 筹码引擎 | 第4周 | 筹码计算引擎 + 衍生指标 + 形态识别 |
| P3: API服务 | 第5周 | REST API + WebSocket + 缓存 |
| P4: 前端 | 第6-7周 | K线图 + 筹码火焰图 + 指标面板 |
| P5: 上线 | 第8周 | Docker部署 + 监控告警 + 文档 |
```
