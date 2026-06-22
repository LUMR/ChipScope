# 单日全市场分时概览页 设计文档

- **日期**：2026-06-22
- **状态**：设计已认可，待写实现计划
- **关联**：依赖「每日全市场分时存档」(`minute_quote` 表, migration 0006) 与 `services/minute_archive.py`

---

## 1. 背景与目标

当前导航有三个 tab：「行情」(`/`，实为个股详情页)、「自选管理」、「数据存档」。`minute_quote` 表已落库全市场分时数据（每只股每天约 240 个分钟点），但**没有任何页面消费它**，也没有读取分时数据的查询接口。

本设计新增一个**「行情」页**，对某个交易日的全市场分时做**聚合概览**，回答「这一天大盘是何时拉升/跳水的、涨跌家数如何演变、某个时刻谁涨得最猛」，并支持从宏观聚合钻取到某时刻榜单、再到个股当天分时。

**两个改动：**
1. 原「行情」tab 改名 **「自选行情」**（路由 `/`、内容不变，仅改标签文字）。
2. 新增 **「行情」tab** → `/market`，即本设计的「单日全市场分时概览页」。

---

## 2. 数据约束（关键）

`minute_quote.data` 是 JSONB 数组 `[{t:"09:31", price, vol}, ...]`，**只有时间、价格、成交量**，无均价线、无成交额、无昨收。算「涨跌幅」必须有**昨收**做基准。

**昨收来源（已实测验证）：** mootdx `stocks(market)` 接口返回列含 `pre_close`（沪市一次返回 2.7 万条，含全市场）。存档流程 `refresh_stock_universe` 本就已调用 `stocks(1)` + `stocks(0)`，**只需把 `pre_close` 一并提取随分时存库**，无需额外 5000 次单股 `quotes` 调用。

**限制：** `stocks` 是实时快照，只能给出「调用那一刻的昨收」。因此：
- **自动 15:30 存档**跑出来的数据：`pre_close` = 当日真实昨收，**准确**。
- **手动补历史日**（`archive_minute_quotes(trade_date=历史日)`）：`stocks().pre_close` 是「今天的昨收」，非历史那天的，**不准确**。
- 降级处理：`pre_close` 缺失/异常（≤0）的股票在聚合时**剔除**；历史补档日在页面标注「昨收为近似值」。

---

## 3. 导航与路由

- `frontend/src/components/TopNav.tsx`：
  - 原 `{ key:"market", label:"行情", onClick: nav("/") }` → 改 `label:"自选行情"`（key、onClick 不变）。
  - 新增 `{ key:"minute", label:"行情", onClick: nav("/market") }`。
  - `activeKey` 逻辑加 `/market` 分支：`pathname.startsWith("/market") → "minute"`。
- `frontend/src/App.tsx`：新增 `<Route path="/market" element={<MarketMinutePage />} />`。

**边界：** 本次「自选行情」仅改标签文字，页面内容（个股详情 + 侧边自选栏）不变。若日后要把该页改成「自选股列表概览」，属另一次改动。

---

## 4. 数据模型与存档

### 4.1 `minute_quote` 加列（migration **0007**）

```python
# backend/app/models/minute_quote.py
pre_close: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
```

migration 0007：`ALTER TABLE minute_quote ADD COLUMN pre_close NUMERIC(12,3) NULL`。

### 4.2 `StockInfo` 加字段

```python
# backend/app/services/collector/types.py
@dataclass(frozen=True)
class StockInfo:
    secucode: str
    code: str
    name: str
    market: str
    secid: str
    pre_close: float | None = None  # 新增，来自 mootdx stocks().pre_close
```

### 4.3 存档流程改动（`services/minute_archive.py`）

- `_filter_a_shares(df, market)`：从 `row["pre_close"]` 提取昨收，填入 `StockInfo.pre_close`（`float(row["pre_close"])` 或 `None`）。
- `upsert_minute_quote(session, trade_date, secucode, points, pre_close)`：行字典加 `"pre_close": pre_close`；ON CONFLICT 的 `set_` 同时更新 `pre_close`。
- `archive_minute_quotes`：`refresh_stock_universe` 返回带 `pre_close` 的 `StockInfo` 列表；遍历时把对应 `pre_close` 透传给 `upsert_minute_quote`（用 `secucode → pre_close` 映射，或让 `refresh_stock_universe` 返回 `StockInfo` 列表后按索引对齐）。

---

## 5. 后端聚合服务（新 `services/market_minute.py`）

纯函数 + NumPy 向量化；DB 读取与缓存为薄封装。

### 5.1 涨跌停与分档判定

```python
_GEM_PREFIXES = {"300", "301", "688", "689"}  # 创业板/科创板：20%

def limit_pct(code: str) -> float:
    """涨跌停幅度（%）。创业板/科创板 20%，主板 10%。ST 暂不识别。"""
    return 20.0 if code[:3] in _GEM_PREFIXES else 10.0

def classify(pct: float, limit: float) -> str:
    """
    返回 limit_up / up / flat / down / limit_down。
    容差 0.3%：pct >= limit-0.3 记涨停；pct <= -limit+0.3 记跌停；
    |pct| < 0.01 记平盘；其余按符号记 up/down。
    """
    if pct >= limit - 0.3:
        return "limit_up"
    if pct <= -limit + 0.3:
        return "limit_down"
    if abs(pct) < 0.01:
        return "flat"
    return "up" if pct > 0 else "down"
```

### 5.2 聚合纯函数

输入：`rows: list[{secucode, code, pre_close, points:[{t,price,vol}]}]`（当日全市场，来自 DB）。

```python
def aggregate(rows) -> dict:
    """
    返回 {
      series: [{t, avg_pct, up, limit_up, flat, down, limit_down}, ...],  # 240 点
      summary: {total, with_pre_close, up, limit_up, flat, down, limit_down}  # 收盘时刻汇总
    }
    """
```

算法（NumPy）：
- 过滤 `pre_close > 0` 的股票；每只构造 `pct_arr = (price/pre_close - 1)*100`，长度对齐 240（停牌/缺失处为 `NaN`）；构造 `limit_arr`（每只的涨跌停幅度）。
- `avg_pct[t] = np.nanmean(pct_mat[:, t])`。
- 家数：对每个时刻，用阈值掩码统计 `limit_up / limit_down`（与各自 limit 比）、`flat`、`up / down`（剩余按符号）。
- `summary` 取最后一个有效时刻的家数与 `total`(rows 数)、`with_pre_close`(参与聚合数)。

### 5.3 钻取纯函数

```python
def ranking_at(rows, time_index: int, n: int = 30) -> dict:
    """该时刻全市场按 pct 排序，返回 {gainers:[{secucode,name,price,pct}], losers:[...]}，各 top n。"""

def stock_series(points, pre_close) -> list[dict]:
    """单股分时加涨跌幅：[{t, price, vol, pct}, ...]。pre_close<=0 时 pct=None。"""
```

### 5.4 DB 读取 + 缓存

```python
async def load_day(session, trade_date: date) -> list[dict]:
    """读当日 minute_quote(data, pre_close) join stock_meta(name)，返回 rows。"""

_overview_cache: dict[date, dict] = {}  # 进程内，历史日期幂等

async def get_overview(session, trade_date) -> dict:
    if trade_date not in _overview_cache:
        rows = await load_day(session, trade_date)
        _overview_cache[trade_date] = aggregate(rows)
    return _overview_cache[trade_date]
```

`ranking` / `stock` 同样可缓存中间 `rows`（按 date 缓存原始 rows，避免重复 DB 读 + JSONB 解析）。

---

## 6. 后端接口（新 `api/market.py`，prefix `/api/market/minute`）

| 方法 | 路径 | 查询参数 | 响应 |
|---|---|---|---|
| GET | `/dates` | — | `["2026-06-18", "2026-06-19", ...]`（distinct trade_date 降序） |
| GET | `/overview` | `date` | `{trade_date, series:[...], summary:{...}}` |
| GET | `/ranking` | `date`, `time`(HH:MM) | `{time, gainers:[{secucode,name,price,pct}], losers:[...]}` |
| GET | `/stock` | `date`, `secucode` | `{secucode, name, pre_close, points:[{t,price,vol,pct}]}` |

- `date` 非法或无数据：`404`（或空结构 + 标注，二选一，实现时定为「无数据返回 404，前端显示空态」）。
- `time` 转时刻索引：`_row_to_time` 的逆（09:31→0 … 15:00→239）；非法 `time` → `422`。
- 在 `app/main.py` 注册 `market.router`。

响应 schema（新 `schemas/market.py`）：`OverviewPointOut`、`OverviewOut`、`RankItemOut`、`RankingOut`、`StockMinutePointOut`、`StockMinuteOut`。

---

## 7. 前端（新 `pages/MarketMinutePage.tsx` + `api/market.ts`）

### 7.1 `api/market.ts`

```ts
export interface OverviewPoint { t: string; avg_pct: number; up:number; limit_up:number; flat:number; down:number; limit_down:number; }
export interface Overview { trade_date: string; series: OverviewPoint[]; summary: {...}; }
export interface RankItem { secucode:string; name:string; price:number; pct:number; }
export interface Ranking { time:string; gainers:RankItem[]; losers:RankItem[]; }
export interface StockMinute { secucode:string; name:string; pre_close:number|null; points:{t:string;price:number;vol:number;pct:number|null}[]; }

export const getMarketDates = () => apiGet<string[]>("/market/minute/dates");
export const getMarketOverview = (date:string) => apiGet<Overview>(`/market/minute/overview?date=${date}`);
export const getMarketRanking = (date:string, time:string) => apiGet<Ranking>(`/market/minute/ranking?date=${date}&time=${time}`);
export const getStockMinute = (date:string, secucode:string) => apiGet<StockMinute>(`/market/minute/stock?date=${date}&secucode=${secucode}`);
```

### 7.2 `MarketMinutePage.tsx`

状态：`date`(默认最新可选日)、`overview`、`ranking`(Modal 数据)、`stock`(Drawer 数据)。

布局：
- **顶部 Card**：`DatePicker`（`disabledDate` 限定为 `/dates` 返回的日）+ 收盘汇总数字（上涨/涨停/平盘/下跌/跌停 家数，来自 `summary`）。
- **主区**：`MarketOverviewChart`（ECharts）。
- 钻取链路见 7.3。

### 7.3 组件与交互

1. **`MarketOverviewChart`** — ECharts 双 grid：
   - `grid[0]`（上，高）：平均涨跌幅折线，`yAxis` 含 0 轴虚线，红涨绿跌；`xAxis` 时间 09:31…15:00。
   - `grid[1]`（下，矮）：五档家数堆叠柱（涨停深红/上涨红/平盘灰/下跌绿/跌停深绿），`xAxis` 与上共享。
   - 点击上折线某点 → 回调 `onPickTime(t)` → 页面拉 `ranking` → 打开 Modal。
2. **`MomentRankingModal`** — AntD `Modal`：两个表格（涨幅前 30 / 跌幅前 30），列 `代码/名称/现价/涨幅`，涨幅红绿。点行 → 回调 `onPickStock(secucode)` → 页面拉 `stock` → 打开 Drawer。
3. **`StockMinuteDrawer`** — AntD `Drawer`（右侧）：该股当天分时小图（ECharts 折线：价格 + 涨幅副轴）+ 名称/代码/pre_close/「该时刻涨幅」标注。

### 7.4 组件文件清单

```
frontend/src/api/market.ts
frontend/src/pages/MarketMinutePage.tsx
frontend/src/components/MarketOverviewChart.tsx
frontend/src/components/MomentRankingModal.tsx
frontend/src/components/StockMinuteDrawer.tsx
```

---

## 8. 性能与缓存

- 聚合 5000 股 × 240 点：NumPy 矩阵运算 < 1s。
- 进程内缓存按 `date`（历史日存档后冻结，幂等）；`overview` 与中间 `rows` 均缓存。当天若盘中查询（未存档）→ 无数据 → 空态。
- 一次 DB 读全市场当日 `data` JSONB（约几 MB），可接受；`ranking`/`stock` 复用缓存的 `rows`，不重复解析。

---

## 9. 测试策略

**后端（纯函数优先，TDD）：** `tests/test_market_minute.py`
- `limit_pct`：主板/创业板/科创板前缀。
- `classify`：涨停边界（limit-0.3）、跌停边界、平盘、涨/跌。
- `aggregate`：合成多股多时刻，验证 `avg_pct`、五档家数；`pre_close<=0` 剔除；停牌（NaN）对齐不污染均值。
- `ranking_at`：取某时刻排序、top n 截断。
- `stock_series`：pct 计算、`pre_close<=0` 时 pct=None。

**后端（接口）：** `tests/test_api_market.py`
- 用真实测试库 fixture 插入若干 `minute_quote` 行（含 `pre_close`），验证 4 个接口返回结构与 404/422。
- mock 非必须（DB 是真实测试库，符合项目约定）。

**前端：** `vitest`
- `MarketMinutePage` 渲染、DatePicker 限选、点击折线点→Modal 打开、点榜单行→Drawer 打开（mock `api/market`）。

---

## 10. 默认值（可在实现期微调）

| 项 | 默认 |
|---|---|
| 聚合基准 | 前一交易日收盘价 `pre_close`（来自 mootdx stocks） |
| 平均方式 | 等权算术平均 |
| 涨跌停幅度 | 创业板/科创板 20%，主板 10%（ST 5% 暂不识别） |
| 涨跌停容差 | 0.3% |
| 平盘阈值 | `|pct| < 0.01%` |
| 榜单 top | 30 涨 + 30 跌 |
| 五档配色 | 涨停#7f1d1d / 上涨#f5222d / 平盘#9ca3af / 下跌#16a34a / 跌停#14532d |

---

## 11. 已知限制 / Follow-up

- **历史补档 pre_close 不准**：`stocks` 是实时快照，仅自动存档日准确；页面标注。
- **ST 涨跌停**（5%）未单独识别（需 `name` 含 "ST"，stocks name 可得），列为 follow-up。
- **不复权**：mootdx 日K/分时不复权，除权日分时跳变。
- **缓存进程内**：重启丢失（可接受，重算成本低）。
- **钻取深度**：到个股分时为止；不进一步钻取筹码（筹码另有页）。

---

## 12. 文件清单

**新建：**
- `backend/alembic/versions/0007_minute_pre_close.py`
- `backend/app/services/market_minute.py`
- `backend/app/api/market.py`
- `backend/app/schemas/market.py`
- `backend/tests/test_market_minute.py`
- `backend/tests/test_api_market.py`
- `frontend/src/api/market.ts`
- `frontend/src/pages/MarketMinutePage.tsx`
- `frontend/src/components/MarketOverviewChart.tsx`
- `frontend/src/components/MomentRankingModal.tsx`
- `frontend/src/components/StockMinuteDrawer.tsx`

**修改：**
- `backend/app/models/minute_quote.py`（+`pre_close`）
- `backend/app/services/collector/types.py`（`StockInfo` +`pre_close`）
- `backend/app/services/minute_archive.py`（提取/透传 `pre_close`）
- `backend/app/main.py`（注册 `market.router`）
- `frontend/src/App.tsx`（`/market` 路由）
- `frontend/src/components/TopNav.tsx`（改名 + 新 tab + activeKey）
- `README.md`（核心功能表 / API 表 / 路线图）
