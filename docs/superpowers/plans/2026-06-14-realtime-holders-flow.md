# ChipScope 实时行情 + 股东/资金流 Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 Plan 1 地基上，新增 mootdx 通达信实时行情（五档盘口）、东方财富十大流通股东 + 资金流向采集，落库并提供 WebSocket 实时推送 + REST 查询 + APScheduler 定时调度。

**Architecture:** mootdx 是同步 TCP 库，用 `ThreadPoolExecutor` 包装进异步；东财 HTTP 客户端加重试退避（应对 Plan 1 暴露的限流）；实时行情走 Redis 缓存 + WebSocket fan-out；调度器作为独立可启动组件（命令行入口），与 API 服务解耦。

**Tech Stack:** mootdx、APScheduler、redis (async)、tenacity（重试）、Plan 1 已有的 FastAPI/SQLAlchemy/asyncpg/httpx。

**关键设计决策：**
1. mootdx 同步调用一律经 `loop.run_in_executor`，不阻塞事件循环。
2. 东财客户端用 tenacity 重试（指数退避），应对限流；同时保持 Plan 1 的 0.5s 节流。
3. 衰减系数 `A = 1/(1 - top10_ratio)` 在 holder_summary 落库时计算（设计文档 4.2）。
4. WebSocket 用连接管理器做 fan-out：单个采集任务刷新 Redis，广播给所有订阅该 code 的连接。
5. 调度器是独立入口 `app.scheduler`，可单独 `python -m app.scheduler` 启动，不耦合 API。

---

## File Structure

```
backend/app/
├── services/
│   ├── collector/
│   │   ├── tdx_client.py          # mootdx 封装（quotes 五档，线程池）
│   │   ├── eastmoney.py           # 追加 holders / money_flow 方法 + 重试
│   │   └── retry.py               # tenacity 重试策略
│   ├── ingest.py                  # 追加 upsert_holders / upsert_money_flow
│   └── realtime.py                # Redis 缓存 + WebSocket 广播
├── api/
│   ├── websocket.py               # /ws/realtime/{code}
│   └── stocks.py                  # 追加 /holders /flow
├── models/
│   ├── holder.py                  # TopHolder, HolderSummary
│   └── flow.py                    # MoneyFlow
├── schemas/
│   ├── holder.py
│   ├── flow.py
│   └── realtime.py                # RealtimeQuote（五档）
├── scheduler.py                   # APScheduler 定时任务入口
└── main.py                        # 挂载 websocket 路由
backend/alembic/versions/0002_holders_flow.py
backend/tests/test_tdx_client.py
backend/tests/test_holders_flow.py
backend/tests/test_realtime.py
```

---

## Task 1: 依赖 + 迁移 0002（股东/资金流表）

**Files:**
- Modify: `backend/requirements.txt`（加 mootdx, apscheduler, tenacity, redis[async]）
- Create: `backend/alembic/versions/0002_holders_flow.py`
- Create: `backend/app/models/holder.py`, `backend/app/models/flow.py`

- [ ] **Step 1: requirements.txt 追加**

```
mootdx>=0.9.0
apscheduler>=3.10.0
tenacity>=8.2.0
```
（redis==5.2.1 Plan 1 已有）

- [ ] **Step 2: 安装**

```bash
.venv/Scripts/pip install "mootdx>=0.9.0" "apscheduler>=3.10.0" "tenacity>=8.2.0"
```

- [ ] **Step 3: models/holder.py**

```python
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class TopHolder(Base):
    __tablename__ = "top_holders"
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    secucode: Mapped[str] = mapped_column(String(12), primary_key=True)
    rank: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    holder_name: Mapped[str] = mapped_column(String(100))
    hold_num: Mapped[int] = mapped_column(BigInteger)
    hold_ratio: Mapped[float] = mapped_column(Numeric(8, 4))
    change_num: Mapped[int] = mapped_column(BigInteger)
    holder_type: Mapped[str | None] = mapped_column(String(20), nullable=True)


class HolderSummary(Base):
    __tablename__ = "holder_summary"
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    secucode: Mapped[str] = mapped_column(String(12), primary_key=True)
    top10_ratio: Mapped[float] = mapped_column(Numeric(8, 4))
    decay_coeff: Mapped[float] = mapped_column(Numeric(6, 2))
    float_shares: Mapped[int] = mapped_column(BigInteger)
```

- [ ] **Step 4: models/flow.py**

```python
from datetime import datetime
from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class MoneyFlow(Base):
    __tablename__ = "money_flow"
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    secucode: Mapped[str] = mapped_column(String(12), primary_key=True)
    main_net: Mapped[float] = mapped_column(Numeric(18, 2))
    super_large_net: Mapped[float] = mapped_column(Numeric(18, 2))
    large_net: Mapped[float] = mapped_column(Numeric(18, 2))
    medium_net: Mapped[float] = mapped_column(Numeric(18, 2))
    small_net: Mapped[float] = mapped_column(Numeric(18, 2))
```

- [ ] **Step 5: 迁移 0002_holders_flow.py**

```python
"""holders and money_flow tables

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"


def upgrade() -> None:
    op.create_table(
        "top_holders",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("holder_name", sa.String(100)),
        sa.Column("hold_num", sa.BigInteger()),
        sa.Column("hold_ratio", sa.Numeric(8, 4)),
        sa.Column("change_num", sa.BigInteger()),
        sa.Column("holder_type", sa.String(20)),
        sa.PrimaryKeyConstraint("secucode", "ts", "rank"),
    )
    op.create_table(
        "holder_summary",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("top10_ratio", sa.Numeric(8, 4)),
        sa.Column("decay_coeff", sa.Numeric(6, 2)),
        sa.Column("float_shares", sa.BigInteger()),
        sa.PrimaryKeyConstraint("secucode", "ts"),
    )
    op.create_table(
        "money_flow",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("main_net", sa.Numeric(18, 2)),
        sa.Column("super_large_net", sa.Numeric(18, 2)),
        sa.Column("large_net", sa.Numeric(18, 2)),
        sa.Column("medium_net", sa.Numeric(18, 2)),
        sa.Column("small_net", sa.Numeric(18, 2)),
        sa.PrimaryKeyConstraint("secucode", "ts"),
    )
    op.execute(
        "SELECT create_hypertable('money_flow', 'ts', "
        "chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);"
    )


def downgrade() -> None:
    op.drop_table("money_flow")
    op.drop_table("holder_summary")
    op.drop_table("top_holders")
```

- [ ] **Step 6: alembic env.py 注册新模型**

在 `alembic/env.py` 的 import 段追加：
```python
import app.models.holder  # noqa: F401
import app.models.flow    # noqa: F401
```

- [ ] **Step 7: 跑迁移 + 验证**

```bash
.venv/Scripts/alembic upgrade head
.venv/Scripts/python -c "
import asyncio
from sqlalchemy import text
from app.database import engine
async def m():
    async with engine.connect() as c:
        print((await c.execute(text(\"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename\"))).fetchall())
    await engine.dispose()
asyncio.run(m())
"
```
Expected: 含 top_holders, holder_summary, money_flow。

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat(db): add holders/money_flow tables + mootdx/apscheduler/tenacity deps"
```

---

## Task 2: mootdx 客户端封装（实时五档，线程池）+ 测试

**Files:** `app/services/collector/tdx_client.py`, `tests/test_tdx_client.py`

mootdx `client.quotes(symbol)` 返回 DataFrame，列含：`price`(现价), `open`, `last_close`(昨收), `high`, `low`, `vol`, `amount`, 及 `buy_price1..5`/`buy_vol1..5`/`sell_price1..5`/`sell_vol1..5`。字段名以实际为准（Step 6 冒烟确认）。

- [ ] **Step 1: 写 tdx_client.py**

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.config import get_settings


@dataclass(frozen=True)
class RealtimeQuote:
    secucode: str
    price: float
    open: float
    last_close: float
    high: float
    low: float
    vol: float       # 总量(手)
    amount: float    # 总额
    bids: list[tuple[float, float]]   # 五档买 (价,量)
    asks: list[tuple[float, float]]   # 五档卖


class TdxClient:
    """mootdx 同步库的异步封装。所有调用走线程池，不阻塞事件循环。"""

    def __init__(self, client=None, executor: ThreadPoolExecutor | None = None) -> None:
        if client is None:
            from mootdx.quotes import Quotes
            client = Quotes.factory(market="std")
        self._client = client
        self._executor = executor or ThreadPoolExecutor(max_workers=4)

    async def quotes(self, symbol: str) -> RealtimeQuote:
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(self._executor, self._client.quotes, symbol)
        return self._parse(df, symbol)

    @staticmethod
    def _parse(df, symbol: str) -> RealtimeQuote:
        row = df.iloc[0]
        bids = [
            (float(row[f"buy_price{i}"]), float(row[f"buy_vol{i}"]))
            for i in range(1, 6)
        ]
        asks = [
            (float(row[f"sell_price{i}"]), float(row[f"sell_vol{i}"]))
            for i in range(1, 6)
        ]
        return RealtimeQuote(
            secucode=symbol,
            price=float(row["price"]),
            open=float(row["open"]),
            last_close=float(row["last_close"]),
            high=float(row["high"]),
            low=float(row["low"]),
            vol=float(row["vol"]),
            amount=float(row["amount"]),
            bids=bids,
            asks=asks,
        )

    def close(self) -> None:
        self._executor.shutdown(wait=False)
```

- [ ] **Step 2: 测试（用假 DataFrame mock mootdx）**

```python
import pandas as pd
import pytest
from app.services.collector.tdx_client import TdxClient


def _fake_df():
    data = {
        "price": [10.5], "open": [10.2], "last_close": [10.3],
        "high": [10.6], "low": [10.1], "vol": [1000.0], "amount": [1050000.0],
    }
    for i in range(1, 6):
        data[f"buy_price{i}"] = [10.4 - i * 0.01]
        data[f"buy_vol{i}"] = [100.0 * i]
        data[f"sell_price{i}"] = [10.6 + i * 0.01]
        data[f"sell_vol{i}"] = [200.0 * i]
    return pd.DataFrame(data)


class _FakeMootdx:
    def quotes(self, symbol):
        return _fake_df()


@pytest.mark.asyncio
async def test_quotes_parses_five_levels():
    client = TdxClient(client=_FakeMootdx(), executor=__import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(max_workers=1))
    q = await client.quotes("600519")
    assert q.price == 10.5
    assert q.secucode == "600519"
    assert len(q.bids) == 5 and len(q.asks) == 5
    assert q.bids[0] == (10.39, 100.0)
    assert q.asks[0] == (10.61, 200.0)
    client.close()
```

- [ ] **Step 3: 运行测试 + Commit**

```bash
.venv/Scripts/python -m pytest tests/test_tdx_client.py -v
git add -A && git commit -m "feat(tdx): mootdx realtime quotes client (async wrapper)"
```

---

## Task 3: 东财重试退避 + 股东客户端 + 测试

**Files:** `app/services/collector/retry.py`, 追加 `eastmoney.py` 的 `fetch_holders` + `fetch_money_flow`, `tests/test_holders_flow.py`

- [ ] **Step 1: retry.py（tenacity 指数退避）**

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx


# 东财限流：指数退避 1s→2s→4s，最多 4 次
em_retry = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TransportError, httpx.RemoteProtocolError, httpx.TimeoutException)),
)
```

- [ ] **Step 2: eastmoney.py 追加 fetch_holders（用 em_retry）**

```python
# 在 EastMoneyClient 类内追加
from app.services.collector.retry import em_retry

    @em_retry
    async def fetch_holders(self, secucode: str) -> list[dict]:
        """十大流通股东。secucode 形如 '600519.SH'。"""
        await self._throttle()
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_F10_EH_FREEHOLDERS",
            "filter": f'(SECUCODE="{secucode}")',
            "columns": "ALL",
            "pageSize": 50,
        }
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return (resp.json().get("result") or {}).get("data") or []
```

- [ ] **Step 3: 测试**

```python
import httpx
import pytest
from app.services.collector.eastmoney import EastMoneyClient


@pytest.mark.asyncio
async def test_fetch_holders_parses(respx_mock):
    respx_mock.get("https://datacenter-web.eastmoney.com/api/data/v1/get").mock(
        return_value=httpx.Response(200, json={"result": {"data": [
            {"HOLDER_NAME": "香港中央结算", "HOLD_NUM": 1000000, "HOLD_RATIO": 5.5,
             "HOLDER_NEW": -10000, "SECUCODE": "600519.SH", "NOTICE_DATE": "2026-03-31"},
        ]}})
    )
    async with EastMoneyClient() as em:
        rows = await em.fetch_holders("600519.SH")
    assert len(rows) == 1
    assert rows[0]["HOLDER_NAME"] == "香港中央结算"


@pytest.mark.asyncio
async def test_fetch_holders_empty(respx_mock):
    respx_mock.get("https://datacenter-web.eastmoney.com/api/data/v1/get").mock(
        return_value=httpx.Response(200, json={"result": None})
    )
    async with EastMoneyClient() as em:
        assert await em.fetch_holders("600519.SH") == []
```

- [ ] **Step 4: 运行 + Commit**

```bash
.venv/Scripts/python -m pytest tests/test_holders_flow.py -v
git add -A && git commit -m "feat(em): holders client with tenacity retry backoff"
```

---

## Task 4: 东财资金流客户端 + 股东/资金流入库 + 测试

**Files:** 追加 `eastmoney.py` 的 `fetch_money_flow`，追加 `ingest.py` 的 `upsert_holders`/`upsert_money_flow`，扩展 `test_holders_flow.py`

- [ ] **Step 1: eastmoney.py 追加 fetch_money_flow**

```python
    @em_retry
    async def fetch_money_flow(self, secid: str, lmt: int = 120) -> list[dict]:
        await self._throttle()
        url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        params = {"secid": secid, "lmt": lmt, "klt": "101",
                  "fields1": "f1,f2,f3,f7",
                  "fields2": "f51,f52,f53,f54,f55,f56,f57,f58"}
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return (resp.json().get("data") or {}).get("klines") or []
```

资金流 klines 行：`日期,主力净额,小单,中单,大单,超大单,主力净占比,...`（字段顺序以实际为准，冒烟确认）。

- [ ] **Step 2: ingest.py 追加 upsert_holders（含衰减系数计算）+ upsert_money_flow**

```python
from app.models.holder import HolderSummary, TopHolder
from app.models.flow import MoneyFlow
from datetime import datetime


async def upsert_holders(session, secucode: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    # 按 NOTICE_DATE 报告期分组，取最新报告期
    rows_sorted = sorted(rows, key=lambda r: r.get("NOTICE_DATE", ""), reverse=True)
    report_date = rows_sorted[0]["NOTICE_DATE"][:10]
    ts = datetime.fromisoformat(report_date).replace(hour=15, minute=30)
    holders = [r for r in rows if r["NOTICE_DATE"][:10] == report_date]

    holder_rows = []
    for i, r in enumerate(holders, 1):
        holder_rows.append({
            "ts": ts, "secucode": secucode, "rank": i,
            "holder_name": r.get("HOLDER_NAME"), "hold_num": int(r.get("HOLD_NUM", 0)),
            "hold_ratio": float(r.get("HOLD_RATIO", 0)),
            "change_num": int(r.get("HOLDER_NEW") or 0),
            "holder_type": r.get("HOLDER_NEWTYPE"),
        })
    top10_ratio = sum(float(r.get("HOLD_RATIO", 0)) for r in holders[:10])
    decay = round(1.0 / (1.0 - top10_ratio / 100.0), 2) if top10_ratio < 100 else 99.0

    stmt_h = insert(TopHolder).values(holder_rows)
    # TopHolder 三列主键冲突更新
    stmt_h = stmt_h.on_conflict_do_update(
        index_elements=[TopHolder.secucode, TopHolder.ts, TopHolder.rank],
        set_={c: stmt_h.excluded[c] for c in holder_rows[0] if c not in ("secucode", "ts", "rank")},
    )
    await session.execute(stmt_h)

    summary_row = {"ts": ts, "secucode": secucode, "top10_ratio": top10_ratio,
                   "decay_coeff": decay, "float_shares": int(holders[0].get("FREE_HOLD_NUM") or 0) if holders else 0}
    stmt_s = insert(HolderSummary).values([summary_row])
    stmt_s = stmt_s.on_conflict_do_update(
        index_elements=[HolderSummary.secucode, HolderSummary.ts],
        set_={c: stmt_s.excluded[c] for c in summary_row if c not in ("secucode", "ts")},
    )
    await session.execute(stmt_s)
    await session.commit()
    return len(holder_rows)
```

- [ ] **Step 3: upsert_money_flow + 解析 + 测试（核心：衰减系数 A=1/(1-top10%)）**

```python
async def upsert_money_flow(session, secucode: str, klines: list[str]) -> int:
    if not klines:
        return 0
    from app.utils.time import trading_day_ts
    rows = []
    for line in klines:
        p = line.split(",")
        rows.append({
            "ts": trading_day_ts(p[0]), "secucode": secucode,
            "main_net": float(p[1]), "small_net": float(p[2]),
            "medium_net": float(p[3]), "large_net": float(p[4]),
            "super_large_net": float(p[5]),
        })
    stmt = insert(MoneyFlow).values(rows)
    first = rows[0]
    stmt = stmt.on_conflict_do_update(
        index_elements=[MoneyFlow.secucode, MoneyFlow.ts],
        set_={c: stmt.excluded[c] for c in first if c not in ("secucode", "ts")},
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)
```

测试 `test_holders_flow.py` 追加：
```python
@pytest.mark.asyncio
async def test_upsert_holders_computes_decay(db_session):
    await upsert_stock_meta(db_session, [StockInfo("600519.SH","600519","贵州茅台","SH","1.600519")])
    rows = [{"NOTICE_DATE":"2026-03-31","HOLDER_NAME":"A","HOLD_NUM":1000,"HOLD_RATIO":50.0,"HOLDER_NEW":0}]
    n = await upsert_holders(db_session, "600519.SH", rows)
    assert n == 1
    from sqlalchemy import select
    s = (await db_session.execute(select(HolderSummary).execution_options(populate_existing=True))).scalars().first()
    assert float(s.top10_ratio) == 50.0
    assert float(s.decay_coeff) == 2.0  # 1/(1-0.5)=2.0
```

- [ ] **Step 4: 运行 + Commit**

```bash
.venv/Scripts/python -m pytest tests/test_holders_flow.py -v
git add -A && git commit -m "feat(ingest): holders (decay coeff) + money_flow upsert"
```

---

## Task 5: REST API（/holders /flow）+ 测试

**Files:** `schemas/holder.py`, `schemas/flow.py`, 追加 `api/stocks.py`

- [ ] **Step 1: schemas + 路由（按 Plan 1 list_stocks 模式）**

```python
# schemas/holder.py
class HolderOut(BaseModel):
    ts: datetime; holder_name: str; hold_ratio: float; rank: int
    model_config = {"from_attributes": True}

# schemas/flow.py
class FlowOut(BaseModel):
    ts: datetime; main_net: float; super_large_net: float
    model_config = {"from_attributes": True}
```

`api/stocks.py` 追加 `GET /{secucode}/holders` 和 `GET /{secucode}/flow`，`select(TopHolder).where(secucode).order_by(rank)` / `select(MoneyFlow).order_by(ts)`。

- [ ] **Step 2: 测试（预置 holder/flow 数据 + 查询）+ Commit**

参照 Plan 1 Task 11 的 api_client fixture（预置数据、override get_db）。断言返回正确条数。

---

## Task 6: Redis 实时缓存 + WebSocket 推送 + 测试

**Files:** `app/services/realtime.py`, `app/api/websocket.py`, 追加 `main.py` 挂载, `tests/test_realtime.py`

- [ ] **Step 1: realtime.py（ConnectionManager fan-out + Redis 读写）**

```python
import json
from fastapi import WebSocket
from app.config import get_settings
import redis.asyncio as aioredis


class ConnectionManager:
    def __init__(self):
        self._subs: dict[str, set[WebSocket]] = {}

    async def connect(self, code: str, ws: WebSocket):
        await ws.accept()
        self._subs.setdefault(code, set()).add(ws)

    def disconnect(self, code: str, ws: WebSocket):
        self._subs.get(code, set()).discard(ws)

    async def broadcast(self, code: str, data: dict):
        dead = []
        for ws in self._subs.get(code, set()):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(code, ws)


manager = ConnectionManager()


async def cache_quote(quote) -> None:
    r = aioredis.from_url(get_settings().redis_url)
    try:
        await r.set(f"quote:{quote.secucode}", json.dumps(quote.__dict__), ex=10)
    finally:
        await r.aclose()
```

- [ ] **Step 2: websocket.py 路由 + main.py 挂载**

```python
# api/websocket.py
from fastapi import APIRouter, WebSocket
from app.services.realtime import manager
router = APIRouter()

@router.websocket("/ws/realtime/{code}")
async def realtime(ws: WebSocket, code: str):
    await manager.connect(code, ws)
    try:
        while True:
            await ws.receive_text()  # 保活
    except Exception:
        manager.disconnect(code, ws)
```

`main.py` 追加 `app.include_router(websocket_router)`。

- [ ] **Step 3: 测试 ConnectionManager（无 Redis，单测 fan-out）+ Commit**

---

## Task 7: APScheduler 调度入口 + 冒烟

**Files:** `app/scheduler.py`

- [ ] **Step 1: scheduler.py**

```python
"""定时调度入口：python -m app.scheduler

- 盘中每 3s 拉取订阅股票实时行情 → Redis + WebSocket 广播
- 每交易日 16:00 采集股东/资金流（东财）
"""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.traders.cron import CronTrigger
from app.services.collector.tdx_client import TdxClient
from app.services.realtime import cache_quote, manager


async def realtime_loop():
    # 简化：实际应订阅动态列表，这里读 Redis 中的自选股
    ...


def main():
    sched = AsyncIOScheduler(timezone="Asia/Shanghai")
    sched.add_job(realtime_loop, "interval", seconds=3, id="realtime")
    sched.add_job(...holders..., CronTrigger(hour=16, minute=0))
    sched.start()
    asyncio.get_event_loop().run_forever()


if __name__ == "__main__":
    main()
```

（具体 holders 调度任务填充：遍历 stock_meta，fetch_holders + upsert，节流。）

- [ ] **Step 2: 冒烟：启动 scheduler 30s 观察实时行情（通达信 TCP，不受东财限流影响）+ Commit**

```bash
PYTHONPATH=. timeout 30 .venv/Scripts/python -m app.scheduler 2>&1 | head -20
```

---

## Task 8: 端到端冒烟（通达信可测，东财视限流）

mootdx 实时行情走通达信，可真实验证；股东/资金流走东财，若仍限流则标注待恢复。

- [ ] 冒烟脚本 `scripts/smoke_realtime.py`：拉茅台实时五档 + 写 Redis + 打印。
- [ ] Commit。

---

## Self-Review

**Spec coverage:** mootdx 实时(Task 2)、股东(Task 3-4)、资金流(Task 4)、衰减系数(Task 4)、WebSocket(Task 6)、调度(Task 7)、API /holders /flow(Task 5)。设计文档 2.2/2.3/4.2/5.2 对应部分覆盖。

**已知风险：**
- mootdx quotes 字段名（buy_price1 等）以实际为准，Task 2 Step 3 冒烟确认。
- 东财资金流 klines 字段顺序以实际为准，Task 4 冒烟确认。
- 东财限流：Task 3 重试退避缓解，但持续限流时股东/资金流真实采集仍受阻（mootdx 实时不受影响）。
- 衰减系数历史回填用最新季度（设计文档已知局限）。

**未覆盖（留给后续 plan）：** 筹码分布引擎（Plan 3）、形态识别（Plan 3）、前端（Plan 4）。
