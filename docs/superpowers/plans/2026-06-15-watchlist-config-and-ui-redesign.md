# 自选股配置页 + UI 重设计 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「自选管理」配置页（搜索添加 / 拖拽排序 / 删除，联动后端 scheduler 监控），并按「现代金融 SaaS」视觉风格重设计全站 UI（左侧常驻自选栏 + 顶部导航 + 实时报价 WebSocket）。

**Architecture:** 后端新增 `watchlist` 表 + CRUD API，scheduler 改为每轮从 DB 读自选股列表（环境变量降级为首次 seed）；新增全局 WebSocket 端点 `/ws/realtime` 单连接推送所有自选股报价。前端引入全局 `AppLayout`（TopNav + SiderWatchlist + Outlet）、`useWatchlist`/`useRealtimeQuotes` hooks、dnd-kit 拖拽表格，AntD ConfigProvider theme token 统一为靛蓝 B 风格。

**Tech Stack:** 后端 FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL + Alembic + Redis；前端 React 19 + TypeScript + react-router v7 + Ant Design 6 + ECharts 6 + dnd-kit + vitest。

---

## 关键约定（所有任务遵循）

- **session 依赖**：`from app.api.deps import get_db`（注意是 `get_db`，不是 `database.get_session`）
- **Base 类**：`from app.models.base import Base`
- **secucode 格式**：`{code}.{market}`（如 `600519.SH`）；`stock_meta.secucode` 是 `String(12)` PK
- **Redis 实时报价 key**：`quote:{secucode}`，value JSON 含 `secucode/price/open/high/low/bids/asks`
- **WebSocket**：现有 `/ws/realtime/{code}`（per-code），本计划新增 `/ws/realtime`（全局）
- **测试隔离**：`conftest.py` 的 TRUNCATE 列表需加入 `watchlist` 表
- **commit message 结尾**：统一加 `Co-Authored-By: Claude <noreply@anthropic.com>`

---

## 文件结构

### 后端新建
- `backend/app/models/watchlist.py` — `Watchlist` ORM 模型
- `backend/app/schemas/watchlist.py` — `WatchlistItemOut` / `WatchlistCreateRequest` / `ReorderRequest`
- `backend/app/api/watchlist.py` — CRUD router
- `backend/alembic/versions/0004_watchlist.py` — 建表 migration
- `backend/tests/test_api_watchlist.py` — API 测试
- `backend/tests/test_scheduler_watchlist.py` — scheduler 读列表测试

### 后端修改
- `backend/app/config.py` — 加 `watchlist_default` 字段
- `backend/app/services/realtime.py` — ConnectionManager 加全局广播
- `backend/app/api/websocket.py` — 新增全局端点 `/ws/realtime`
- `backend/app/scheduler.py` — realtime_loop 从 DB 读 + seed 逻辑
- `backend/app/main.py` — 注册 watchlist router
- `backend/alembic/env.py` — import watchlist 模型
- `backend/tests/conftest.py` — TRUNCATE 加 watchlist

### 前端新建
- `frontend/src/api/watchlist.ts` — watchlist API 调用
- `frontend/src/hooks/useWatchlist.ts` — CRUD hook
- `frontend/src/hooks/useRealtimeQuotes.ts` — WS hook + Provider + Context
- `frontend/src/components/AppLayout.tsx` — 全局布局
- `frontend/src/components/TopNav.tsx` — 顶部导航
- `frontend/src/components/SiderWatchlist.tsx` — 常驻自选栏（替代旧 Watchlist）
- `frontend/src/pages/WatchlistPage.tsx` — 配置页
- `frontend/src/hooks/useWatchlist.test.ts` / `useRealtimeQuotes.test.ts` — hook 测试

### 前端修改
- `frontend/src/api/client.ts` — 加 `apiPost/apiDelete/apiPut`
- `frontend/src/types/domain.ts` — 加 watchlist/quote 类型
- `frontend/src/App.tsx` — AppLayout 路由 + `/watchlist`
- `frontend/src/main.tsx` — ConfigProvider theme token + RealtimeProvider
- `frontend/src/pages/StockDetail.tsx` — 移除自带 Layout，只留 Content
- `frontend/src/index.css` — B 风格 CSS 变量
- `frontend/package.json` — 加 @dnd-kit 依赖

---

## 阶段一：后端 watchlist 数据层

### Task 1: Watchlist ORM 模型

**Files:**
- Create: `backend/app/models/watchlist.py`

- [ ] **Step 1: 写模型**

```python
# backend/app/models/watchlist.py
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    secucode: Mapped[str] = mapped_column(
        String(12), ForeignKey("stock_meta.secucode"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 2: 提交**

```bash
git add backend/app/models/watchlist.py
git commit -m "feat(db): add Watchlist model

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Alembic migration + env.py 注册

**Files:**
- Create: `backend/alembic/versions/0004_watchlist.py`
- Modify: `backend/alembic/env.py`（加 `import app.models.watchlist  # noqa: F401`）

- [ ] **Step 1: 写 migration**

```python
# backend/alembic/versions/0004_watchlist.py
"""add watchlist table

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["secucode"], ["stock_meta.secucode"]),
        sa.UniqueConstraint("scope", "secucode", name="uq_watchlist_scope_secucode"),
    )
    op.create_index(
        "ix_watchlist_scope_sort_order", "watchlist", ["scope", "sort_order"]
    )


def downgrade() -> None:
    op.drop_table("watchlist")
```

- [ ] **Step 2: env.py 注册模型** — 在 `backend/alembic/env.py` 现有 `import app.models.chip  # noqa: F401` 之后加一行：

```python
import app.models.watchlist  # noqa: F401
```

- [ ] **Step 3: 应用 migration 验证**

```bash
cd backend && alembic upgrade head
```
Expected: 输出 `Running upgrade 0003 -> 0004, add watchlist table`，无报错。

- [ ] **Step 4: 提交**

```bash
git add backend/alembic/versions/0002_watchlist.py backend/alembic/env.py
git commit -m "feat(db): watchlist migration 0002

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Watchlist schemas

**Files:**
- Create: `backend/app/schemas/watchlist.py`

- [ ] **Step 1: 写 schemas**

```python
# backend/app/schemas/watchlist.py
from datetime import datetime

from pydantic import BaseModel


class WatchlistItemOut(BaseModel):
    """自选项：股票元数据 + 实时报价（报价可能为空）。"""
    secucode: str
    code: str
    name: str
    industry: str | None = None
    sort_order: int
    created_at: datetime
    price: float | None = None
    pct_change: float | None = None

    model_config = {"from_attributes": True}


class WatchlistCreateRequest(BaseModel):
    secucode: str


class ReorderRequest(BaseModel):
    secucodes: list[str]
```

- [ ] **Step 2: 提交**

```bash
git add backend/app/schemas/watchlist.py
git commit -m "feat(api): watchlist schemas

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 更新 conftest TRUNCATE 列表

**Files:**
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: 在两处 TRUNCATE 语句的表列表里加 `watchlist`** — 把 `"...chip_distribution CASCADE"` 改为 `"...chip_distribution, watchlist CASCADE"`（conftest.py 中有两处 TRUNCATE，前后各一处）。

- [ ] **Step 2: 提交**

```bash
git add backend/tests/conftest.py
git commit -m "test(db): include watchlist in TRUNCATE isolation

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Watchlist API router（TDD）

**Files:**
- Create: `backend/app/api/watchlist.py`
- Modify: `backend/app/main.py`（注册 router）
- Test: `backend/tests/test_api_watchlist.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_api_watchlist.py
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.stock import StockMeta


@pytest_asyncio.fixture
async def watchlist_client():
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE stock_meta, watchlist CASCADE"
        ))
    async with SessionLocal() as s:
        s.add_all([
            StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                      market="SH", secid="1.600519", industry="白酒"),
            StockMeta(secucode="000001.SZ", code="000001", name="平安银行",
                      market="SZ", secid="0.000001", industry="银行"),
        ])
        await s.commit()

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    from app.api.deps import get_db
    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stock_meta, watchlist CASCADE"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_empty_watchlist(watchlist_client):
    r = await watchlist_client.get("/api/watchlist")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_add_and_list(watchlist_client):
    r = await watchlist_client.post("/api/watchlist", json={"secucode": "600519.SH"})
    assert r.status_code == 201
    r = await watchlist_client.post("/api/watchlist", json={"secucode": "000001.SZ"})
    assert r.status_code == 201

    r = await watchlist_client.get("/api/watchlist")
    data = r.json()
    assert len(data) == 2
    assert data[0]["secucode"] == "600519.SH"
    assert data[0]["name"] == "贵州茅台"
    assert data[0]["industry"] == "白酒"
    assert data[0]["sort_order"] == 0
    assert data[1]["sort_order"] == 1


@pytest.mark.asyncio
async def test_add_duplicate_ignored(watchlist_client):
    await watchlist_client.post("/api/watchlist", json={"secucode": "600519.SH"})
    r = await watchlist_client.post("/api/watchlist", json={"secucode": "600519.SH"})
    assert r.status_code == 201  # 幂等：已存在也算成功
    r = await watchlist_client.get("/api/watchlist")
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_add_unknown_secucode_400(watchlist_client):
    r = await watchlist_client.post("/api/watchlist", json={"secucode": "999999.XX"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete(watchlist_client):
    await watchlist_client.post("/api/watchlist", json={"secucode": "600519.SH"})
    r = await watchlist_client.delete("/api/watchlist/600519.SH")
    assert r.status_code == 204
    r = await watchlist_client.get("/api/watchlist")
    assert r.json() == []


@pytest.mark.asyncio
async def test_reorder(watchlist_client):
    await watchlist_client.post("/api/watchlist", json={"secucode": "600519.SH"})
    await watchlist_client.post("/api/watchlist", json={"secucode": "000001.SZ"})
    r = await watchlist_client.put(
        "/api/watchlist/reorder",
        json={"secucodes": ["000001.SZ", "600519.SH"]},
    )
    assert r.status_code == 204
    data = (await watchlist_client.get("/api/watchlist")).json()
    assert data[0]["secucode"] == "000001.SZ"
    assert data[0]["sort_order"] == 0
    assert data[1]["secucode"] == "600519.SH"
    assert data[1]["sort_order"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && pytest tests/test_api_watchlist.py -v
```
Expected: FAIL（`/api/watchlist` 路由不存在，404）。

- [ ] **Step 3: 写 router 实现**

```python
# backend/app/api/watchlist.py
import json

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import get_settings
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.schemas.watchlist import ReorderRequest, WatchlistCreateRequest, WatchlistItemOut

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

SCOPE = "default"


async def _read_quote(secucode: str) -> dict | None:
    r = aioredis.from_url(get_settings().redis_url)
    try:
        raw = await r.get(f"quote:{secucode}")
        return json.loads(raw) if raw else None
    finally:
        await r.aclose()


@router.get("", response_model=list[WatchlistItemOut])
async def list_watchlist(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Watchlist, StockMeta)
        .join(StockMeta, Watchlist.secucode == StockMeta.secucode)
        .where(Watchlist.scope == SCOPE)
        .order_by(Watchlist.sort_order)
    )
    rows = (await db.execute(stmt)).all()
    out: list[WatchlistItemOut] = []
    for w, s in rows:
        q = await _read_quote(w.secucode)
        out.append(WatchlistItemOut(
            secucode=w.secucode,
            code=s.code,
            name=s.name,
            industry=s.industry,
            sort_order=w.sort_order,
            created_at=w.created_at,
            price=q.get("price") if q else None,
            pct_change=None,  # quote 缓存暂无 pct_change，留空
        ))
    return out


@router.post("", response_model=WatchlistItemOut, status_code=201)
async def add_watchlist(
    body: WatchlistCreateRequest, db: AsyncSession = Depends(get_db)
):
    exists = (
        await db.execute(select(StockMeta).where(StockMeta.secucode == body.secucode))
    ).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=400, detail="secucode not in stock_meta")

    max_order = (
        await db.execute(
            select(func.coalesce(func.max(Watchlist.sort_order), -1)).where(
                Watchlist.scope == SCOPE
            )
        )
    ).scalar_one()
    stmt = (
        insert(Watchlist)
        .values(secucode=body.secucode, scope=SCOPE, sort_order=max_order + 1)
        .on_conflict_do_nothing(index_elements=[Watchlist.scope, Watchlist.secucode])
    )
    await db.execute(stmt)
    await db.commit()

    row = (
        await db.execute(
            select(Watchlist).where(
                Watchlist.scope == SCOPE, Watchlist.secucode == body.secucode
            )
        )
    ).scalar_one()
    return WatchlistItemOut(
        secucode=row.secucode,
        code=exists.code,
        name=exists.name,
        industry=exists.industry,
        sort_order=row.sort_order,
        created_at=row.created_at,
    )


@router.delete("/{secucode}", status_code=204)
async def delete_watchlist(secucode: str, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(Watchlist).where(
                Watchlist.scope == SCOPE, Watchlist.secucode == secucode
            )
        )
    ).scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return Response(status_code=204)


@router.put("/reorder", status_code=204)
async def reorder_watchlist(
    body: ReorderRequest, db: AsyncSession = Depends(get_db)
):
    for idx, secucode in enumerate(body.secucodes):
        row = (
            await db.execute(
                select(Watchlist).where(
                    Watchlist.scope == SCOPE, Watchlist.secucode == secucode
                )
            )
        ).scalar_one_or_none()
        if row:
            row.sort_order = idx
    await db.commit()
    return Response(status_code=204)
```

- [ ] **Step 4: 注册 router** — 在 `backend/app/main.py` 加 import 和 include：

```python
from app.api.watchlist import router as watchlist_router
# ...
app.include_router(watchlist_router)
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd backend && pytest tests/test_api_watchlist.py -v
```
Expected: 6 passed。

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/watchlist.py backend/app/main.py backend/tests/test_api_watchlist.py
git commit -m "feat(api): watchlist CRUD endpoints

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Config seed 配置

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: 加字段** — 在 `Settings` 类的 `eastmoney_user_agent` 字段后加：

```python
    # 自选股默认种子（逗号分隔 secucode），watchlist 表为空时首次写入
    watchlist_default: str = "600519.SH,000001.SZ,000858.SZ,601318.SH,002594.SZ"
```

- [ ] **Step 2: 提交**

```bash
git add backend/app/config.py
git commit -m "feat(config): add watchlist_default seed setting

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 阶段二：后端实时联动

### Task 7: ConnectionManager 全局广播 + 全局 WS 端点

**Files:**
- Modify: `backend/app/services/realtime.py`
- Modify: `backend/app/api/websocket.py`

- [ ] **Step 1: 给 ConnectionManager 加全局订阅** — 在 `backend/app/services/realtime.py` 的 `ConnectionManager.__init__` 加 `self._global_subs: set[WebSocket] = set()`，并在类里加三个方法：

```python
    async def connect_global(self, ws: WebSocket) -> None:
        await ws.accept()
        self._global_subs.add(ws)

    def disconnect_global(self, ws: WebSocket) -> None:
        self._global_subs.discard(ws)

    async def broadcast_global(self, data: dict) -> None:
        """广播给所有全局订阅者（单连接收全部自选股）。"""
        dead: list[WebSocket] = []
        for ws in list(self._global_subs):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_global(ws)
```

- [ ] **Step 2: 加全局 WS 端点** — 在 `backend/app/api/websocket.py` 现有 per-code 端点之后加：

```python
@router.websocket("/ws/realtime")
async def realtime_all(ws: WebSocket):
    """全局订阅：单连接接收所有自选股实时行情。消息含 secucode 字段。"""
    await manager.connect_global(ws)
    try:
        while True:
            await ws.receive_text()
    except Exception:
        manager.disconnect_global(ws)
```

- [ ] **Step 3: 手动冒烟（可选）** — 启动 `uvicorn app.main:app --port 8001`，用浏览器调试工具连 `ws://localhost:8001/ws/realtime`，确认连接成功（无 scheduler 推送时无消息，正常）。

- [ ] **Step 4: 提交**

```bash
git add backend/app/services/realtime.py backend/app/api/websocket.py
git commit -m "feat(ws): global realtime endpoint + broadcast

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: scheduler 从 DB 读 watchlist + seed（TDD）

**Files:**
- Modify: `backend/app/scheduler.py`
- Test: `backend/tests/test_scheduler_watchlist.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_scheduler_watchlist.py
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist


@pytest_asyncio.fixture
async def db_with_watchlist():
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stock_meta, watchlist CASCADE"))
    async with SessionLocal() as s:
        s.add_all([
            StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                      market="SH", secid="1.600519"),
            StockMeta(secucode="000001.SZ", code="000001", name="平安银行",
                      market="SZ", secid="0.000001"),
        ])
        await s.commit()
    yield SessionLocal
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stock_meta, watchlist CASCADE"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_read_watchlist_codes(db_with_watchlist):
    SessionLocal = db_with_watchlist
    async with SessionLocal() as s:
        s.add_all([
            Watchlist(secucode="600519.SH", scope="default", sort_order=1),
            Watchlist(secucode="000001.SZ", scope="default", sort_order=0),
        ])
        await s.commit()

    from app.scheduler import read_watchlist_secucodes
    codes = await read_watchlist_secucodes()
    assert codes == ["000001.SZ", "600519.SH"]  # 按 sort_order


@pytest.mark.asyncio
async def test_seed_when_empty(db_with_watchlist):
    from app.scheduler import seed_watchlist_if_empty
    n = await seed_watchlist_if_empty()
    assert n >= 1  # 至少种入存在于 stock_meta 的
    from app.scheduler import read_watchlist_secucodes
    codes = await read_watchlist_secucodes()
    assert "600519.SH" in codes
    # 再 seed 不重复
    n2 = await seed_watchlist_if_empty()
    assert n2 == 0
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && pytest tests/test_scheduler_watchlist.py -v
```
Expected: FAIL（`read_watchlist_secucodes` 未定义）。

- [ ] **Step 3: 改造 scheduler** — 用下面的内容替换 `backend/app/scheduler.py` 顶部到 `realtime_loop` 之前的部分（保留 daily_holders_flow、_amain、main 不变），核心改动：删除模块级 `WATCHLIST`，新增两个函数，realtime_loop 每轮从 DB 读：

```python
# backend/app/scheduler.py（顶部 imports + 新增函数）
"""定时调度入口：python -m app.scheduler

- 盘中每 3s 拉取自选股（DB watchlist 表）实时行情 → Redis 缓存 + WebSocket 广播
- 每交易日 16:00 采集股东 + 资金流（东财）
- watchlist 表为空时，用 CHIPSCOPE_WATCHLIST_DEFAULT 环境变量 seed
"""
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.tdx_client import TdxClient
from app.services.ingest import upsert_holders, upsert_money_flow
from app.services.realtime import cache_quote, manager

SCOPE = "default"


async def read_watchlist_secucodes() -> list[str]:
    """按 sort_order 读取当前自选股 secucode 列表。"""
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Watchlist.secucode)
                .where(Watchlist.scope == SCOPE)
                .order_by(Watchlist.sort_order)
            )
        ).scalars().all()
    return list(rows)


async def seed_watchlist_if_empty() -> int:
    """watchlist 表为空时，用配置的默认种子初始化（仅插入已存在于 stock_meta 的）。返回插入行数。"""
    async with SessionLocal() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(Watchlist).where(
                    Watchlist.scope == SCOPE
                )
            )
        ).scalar_one()
        if count > 0:
            return 0
        existing = set(
            (
                await session.execute(select(StockMeta.secucode))
            ).scalars().all()
        )
        seeds = [
            c.strip()
            for c in get_settings().watchlist_default.split(",")
            if c.strip() and c.strip() in existing
        ]
        for i, secucode in enumerate(seeds):
            session.add(Watchlist(secucode=secucode, scope=SCOPE, sort_order=i))
        await session.commit()
        return len(seeds)


async def realtime_loop() -> None:
    """盘中实时刷新：每轮从 DB 读自选股，拉行情 → Redis + 全局广播。"""
    secucodes = await read_watchlist_secucodes()
    if not secucodes:
        return
    tdx = TdxClient()
    try:
        for secucode in secucodes:
            code = secucode.split(".")[0]
            try:
                q = await tdx.quotes(code)
                await cache_quote(q)
                await manager.broadcast_global(
                    {
                        "secucode": secucode,
                        "price": q.price,
                        "bids": q.bids,
                        "asks": q.asks,
                    }
                )
            except Exception as e:  # 单只失败不影响其他
                print(f"[realtime] {secucode} error: {e}")
    finally:
        tdx.close()
```

并在 `_amain` 的 `sched.start()` 之前加 seed 调用：

```python
    await seed_watchlist_if_empty()
    sched = AsyncIOScheduler(timezone="Asia/Shanghai")
    # ...（保持原有 add_job 不变）
    sched.start()
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd backend && pytest tests/test_scheduler_watchlist.py -v
```
Expected: 2 passed。

- [ ] **Step 5: 跑全量后端测试确认无回归**

```bash
cd backend && pytest -q
```
Expected: 全部 passed（原有 46 + 新增 8）。

- [ ] **Step 6: 提交**

```bash
git add backend/app/scheduler.py backend/tests/test_scheduler_watchlist.py
git commit -m "feat(scheduler): read watchlist from DB + seed

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 阶段三：前端基础

### Task 9: 安装 dnd-kit 依赖

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: 安装**

```bash
cd frontend && npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
```

- [ ] **Step 2: 提交**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "deps(fe): add @dnd-kit for watchlist drag-sort

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: api client 加 POST/DELETE/PUT

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: 在 `apiGet` 之后追加**

```typescript
// frontend/src/api/client.ts（追加到文件末尾）

export async function apiPost<T>(
  path: string,
  body?: unknown
): Promise<T> {
  const resp = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    throw new Error(`API POST ${path}: ${resp.status}`);
  }
  return resp.status === 204 ? (undefined as T) : (resp.json() as Promise<T>);
}

export async function apiDelete<T>(path: string): Promise<T> {
  const resp = await fetch(BASE + path, { method: "DELETE" });
  if (!resp.ok) {
    throw new Error(`API DELETE ${path}: ${resp.status}`);
  }
  return resp.status === 204 ? (undefined as T) : (resp.json() as Promise<T>);
}

export async function apiPut<T>(
  path: string,
  body?: unknown
): Promise<T> {
  const resp = await fetch(BASE + path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    throw new Error(`API PUT ${path}: ${resp.status}`);
  }
  return resp.status === 204 ? (undefined as T) : (resp.json() as Promise<T>);
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(fe): add apiPost/apiDelete/apiPut

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: domain 类型 + watchlist API 调用

**Files:**
- Modify: `frontend/src/types/domain.ts`
- Create: `frontend/src/api/watchlist.ts`

- [ ] **Step 1: 加类型** — 在 `frontend/src/types/domain.ts` 末尾追加：

```typescript
export interface WatchlistItem {
  secucode: string;
  code: string;
  name: string;
  industry: string | null;
  sort_order: number;
  created_at: string;
  price: number | null;
  pct_change: number | null;
}

export interface RealtimeQuote {
  secucode: string;
  price: number;
  bids: unknown;
  asks: unknown;
}
```

- [ ] **Step 2: 写 watchlist API**

```typescript
// frontend/src/api/watchlist.ts
import { apiDelete, apiGet, apiPost, apiPut } from "./client";
import type { WatchlistItem } from "../types/domain";

export const getWatchlist = () => apiGet<WatchlistItem[]>("/watchlist");

export const addWatchlist = (secucode: string) =>
  apiPost<WatchlistItem>("/watchlist", { secucode });

export const removeWatchlist = (secucode: string) =>
  apiDelete<void>(`/watchlist/${secucode}`);

export const reorderWatchlist = (secucodes: string[]) =>
  apiPut<void>("/watchlist/reorder", { secucodes });
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/types/domain.ts frontend/src/api/watchlist.ts
git commit -m "feat(fe): watchlist types + api calls

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 阶段四：前端 hooks

### Task 12: useWatchlist hook（TDD）

**Files:**
- Create: `frontend/src/hooks/useWatchlist.ts`
- Test: `frontend/src/hooks/useWatchlist.test.ts`

- [ ] **Step 1: 写失败测试**

```typescript
// frontend/src/hooks/useWatchlist.test.ts
import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useWatchlist } from "./useWatchlist";

vi.mock("../api/watchlist", () => ({
  getWatchlist: vi.fn(),
  addWatchlist: vi.fn(),
  removeWatchlist: vi.fn(),
  reorderWatchlist: vi.fn(),
}));

import { getWatchlist, addWatchlist, removeWatchlist, reorderWatchlist } from "../api/watchlist";

const ITEM = (secucode: string, sort_order: number) => ({
  secucode, code: secucode.split(".")[0], name: secucode, industry: null,
  sort_order, created_at: "2026-06-15T00:00:00Z", price: null, pct_change: null,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getWatchlist).mockResolvedValue([ITEM("600519.SH", 0), ITEM("000001.SZ", 1)]);
});

describe("useWatchlist", () => {
  it("loads items on mount", async () => {
    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
  });

  it("add reloads list", async () => {
    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    vi.mocked(addWatchlist).mockResolvedValue(ITEM("000858.SZ", 2));
    vi.mocked(getWatchlist).mockResolvedValue([
      ITEM("600519.SH", 0), ITEM("000001.SZ", 1), ITEM("000858.SZ", 2),
    ]);
    await act(async () => { await result.current.add("000858.SZ"); });
    await waitFor(() => expect(result.current.items).toHaveLength(3));
    expect(addWatchlist).toHaveBeenCalledWith("000858.SZ");
  });

  it("remove does optimistic delete + persists", async () => {
    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    vi.mocked(removeWatchlist).mockResolvedValue(undefined);
    await act(async () => { await result.current.remove("600519.SH"); });
    expect(removeWatchlist).toHaveBeenCalledWith("600519.SH");
    await waitFor(() =>
      expect(result.current.items.find((i) => i.secucode === "600519.SH")).toBeUndefined()
    );
  });

  it("reorder persists new order", async () => {
    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    vi.mocked(reorderWatchlist).mockResolvedValue(undefined);
    await act(async () => {
      await result.current.reorder(["000001.SZ", "600519.SH"]);
    });
    expect(reorderWatchlist).toHaveBeenCalledWith(["000001.SZ", "600519.SH"]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/hooks/useWatchlist.test.ts
```
Expected: FAIL（`useWatchlist` 未定义）。

- [ ] **Step 3: 写 hook**

```typescript
// frontend/src/hooks/useWatchlist.ts
import { useCallback, useEffect, useState } from "react";
import {
  addWatchlist,
  getWatchlist,
  removeWatchlist,
  reorderWatchlist,
} from "../api/watchlist";
import type { WatchlistItem } from "../types/domain";

export function useWatchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await getWatchlist());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const add = useCallback(async (secucode: string) => {
    await addWatchlist(secucode);
    await reload();
  }, [reload]);

  const remove = useCallback(async (secucode: string) => {
    const prev = items;
    setItems((cur) => cur.filter((i) => i.secucode !== secucode));
    try {
      await removeWatchlist(secucode);
    } catch {
      setItems(prev); // 回滚
    }
  }, [items]);

  const reorder = useCallback(async (secucodes: string[]) => {
    const prev = items;
    const map = new Map(prev.map((i) => [i.secucode, i]));
    setItems(secucodes.map((s) => map.get(s)!).filter(Boolean));
    try {
      await reorderWatchlist(secucodes);
    } catch {
      setItems(prev);
    }
  }, [items]);

  return { items, loading, add, remove, reorder, reload };
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && npx vitest run src/hooks/useWatchlist.test.ts
```
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/hooks/useWatchlist.ts frontend/src/hooks/useWatchlist.test.ts
git commit -m "feat(fe): useWatchlist hook with optimistic updates

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 13: useRealtimeQuotes hook + Provider（TDD）

**Files:**
- Create: `frontend/src/hooks/useRealtimeQuotes.ts`
- Test: `frontend/src/hooks/useRealtimeQuotes.test.ts`

- [ ] **Step 1: 写失败测试（mock WebSocket）**

```typescript
// frontend/src/hooks/useRealtimeQuotes.test.ts
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { RealtimeProvider, useQuote, useAllQuotes } from "./useRealtimeQuotes";
import type { ReactNode } from "react";

class MockWS {
  static instances: MockWS[] = [];
  url: string;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  readyState = 1;
  constructor(url: string) {
    this.url = url;
    MockWS.instances.push(this);
  }
  send() {}
  close() { this.readyState = 3; }
  emit(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

beforeEach(() => {
  MockWS.instances = [];
  (globalThis as unknown as { WebSocket: typeof MockWS }).WebSocket = MockWS;
});
afterEach(() => vi.clearAllMocks());

const wrapper = ({ children }: { children: ReactNode }) =>
  <RealtimeProvider>{children}</RealtimeProvider>;

describe("useRealtimeQuotes", () => {
  it("connects to /ws/realtime and routes quotes by secucode", async () => {
    // useQuote 与 useAllQuotes 必须在同一 Provider 实例下，否则 context 各自独立
    const { result } = renderHook(
      () => ({ q: useQuote("600519.SH"), all: useAllQuotes() }),
      { wrapper }
    );
    await waitFor(() => expect(MockWS.instances).toHaveLength(1));
    expect(MockWS.instances[0].url).toContain("/ws/realtime");

    MockWS.instances[0].emit({ secucode: "600519.SH", price: 1689.5 });
    await waitFor(() => expect(result.current.q?.price).toBe(1689.5));

    MockWS.instances[0].emit({ secucode: "000001.SZ", price: 11.2 });
    await waitFor(() => expect(Object.keys(result.current.all)).toHaveLength(2));
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/hooks/useRealtimeQuotes.test.ts
```
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 写 hook + Provider**

```typescript
// frontend/src/hooks/useRealtimeQuotes.ts
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { RealtimeQuote } from "../types/domain";

type QuoteMap = Record<string, RealtimeQuote>;

const QuoteContext = createContext<QuoteMap>({});

function wsUrl() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/realtime`;
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [quotes, setQuotes] = useState<QuoteMap>({});

  useEffect(() => {
    let retry = 1000;
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;
    let ws: WebSocket;

    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as RealtimeQuote;
          if (data.secucode) {
            setQuotes((prev) => ({ ...prev, [data.secucode]: data }));
          }
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        if (closed) return;
        timer = setTimeout(connect, retry);
        retry = Math.min(retry * 2, 15000); // 指数退避，上限 15s
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return (
    <QuoteContext.Provider value={quotes}>{children}</QuoteContext.Provider>
  );
}

export function useQuote(secucode: string): RealtimeQuote | undefined {
  return useContext(QuoteContext)[secucode];
}

export function useAllQuotes(): QuoteMap {
  return useContext(QuoteContext);
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && npx vitest run src/hooks/useRealtimeQuotes.test.ts
```
Expected: passed。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/hooks/useRealtimeQuotes.ts frontend/src/hooks/useRealtimeQuotes.test.ts
git commit -m "feat(fe): useRealtimeQuotes + global WS provider

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 阶段五：前端布局与页面

### Task 14: AppLayout + 路由 + StockDetail 改造

**Files:**
- Create: `frontend/src/components/AppLayout.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/StockDetail.tsx`（移除自带 Layout，只留 Content 区块）

- [ ] **Step 1: 写 AppLayout**

```tsx
// frontend/src/components/AppLayout.tsx
import { Layout } from "antd";
import { Outlet } from "react-router-dom";
import SiderWatchlist from "./SiderWatchlist";
import TopNav from "./TopNav";

const { Header, Sider, Content } = Layout;

export default function AppLayout() {
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header style={{ background: "#fff", padding: "0 24px", height: 56 }}>
        <TopNav />
      </Header>
      <Layout>
        <Sider width={220} theme="light" style={{ borderRight: "1px solid #f0f0f0" }}>
          <SiderWatchlist />
        </Sider>
        <Content style={{ padding: 16, background: "#f6f7f9" }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
```

- [ ] **Step 2: 改路由** — 用下面内容替换 `frontend/src/App.tsx`：

```tsx
// frontend/src/App.tsx
import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import StockDetail from "./pages/StockDetail";
import WatchlistPage from "./pages/WatchlistPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/stock/600519.SH" replace />} />
        <Route path="/stock/:secucode" element={<StockDetail />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 3: 精简 StockDetail** — 用下面内容替换 `frontend/src/pages/StockDetail.tsx`（移除 Layout/Header/Sider，只保留原 Content 内的区块）：

```tsx
// frontend/src/pages/StockDetail.tsx
import { useEffect, useState } from "react";
import { Alert, Spin } from "antd";
import { useParams } from "react-router-dom";
import ChipFlame from "../components/ChipFlame";
import DateSlider from "../components/DateSlider";
import KLineChart from "../components/KLineChart";
import MetricPanel from "../components/MetricPanel";
import { getChips } from "../api/stocks";
import { useStockData } from "../hooks/useStockData";
import type { ChipDistribution } from "../types/domain";

export default function StockDetail() {
  const { secucode = "600519.SH" } = useParams();
  const { kline, pattern, loading, error } = useStockData(secucode);
  const [dateIdx, setDateIdx] = useState(0);
  const [chip, setChip] = useState<ChipDistribution | undefined>();

  const dates = kline.map((k) => k.ts.slice(0, 10));

  useEffect(() => {
    setDateIdx(Math.max(0, dates.length - 1));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secucode]);

  useEffect(() => {
    if (dates.length === 0) {
      setChip(undefined);
      return;
    }
    const d = dates[dateIdx];
    let cancelled = false;
    getChips(secucode, d)
      .then((rows) => {
        if (!cancelled) setChip(rows[0]);
      })
      .catch(() => {
        if (!cancelled) setChip(undefined);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secucode, dateIdx, dates.length]);

  if (loading) return <Spin />;
  if (error) return <Alert type="error" message={error} />;

  return (
    <>
      <KLineChart bars={kline} />
      <DateSlider dates={dates} value={dateIdx} onChange={setDateIdx} />
      <ChipFlame chip={chip} />
      <div style={{ marginTop: 16 }}>
        <MetricPanel chip={chip} pattern={pattern} />
      </div>
    </>
  );
}
```

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/AppLayout.tsx frontend/src/App.tsx frontend/src/pages/StockDetail.tsx
git commit -m "feat(fe): global AppLayout + routes + slim StockDetail

Co-Authored-By: Claude <noreply@anthropic.com>"
```

> 注：此 task 后应用暂时无法编译（TopNav/SiderWatchlist/WatchlistPage 尚未创建），下一个 task 起补齐。这是预期的增量进度。

---

### Task 15: TopNav 组件

**Files:**
- Create: `frontend/src/components/TopNav.tsx`

- [ ] **Step 1: 写组件**（从旧 Header.tsx 的搜索逻辑提取，加导航菜单）

```tsx
// frontend/src/components/TopNav.tsx
import { AutoComplete, Input, Menu } from "antd";
import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { listStocks } from "../api/stocks";
import type { Stock } from "../types/domain";

export default function TopNav() {
  const nav = useNavigate();
  const loc = useLocation();
  const [opts, setOpts] = useState<{ value: string; label: string }[]>([]);
  const [text, setText] = useState("");

  const activeKey = loc.pathname.startsWith("/watchlist") ? "watchlist" : "market";

  useEffect(() => {
    if (!text) {
      setOpts([]);
      return;
    }
    let cancelled = false;
    listStocks(text)
      .then((stocks: Stock[]) => {
        if (cancelled) return;
        setOpts(
          stocks.map((s) => ({ value: s.secucode, label: `${s.name} ${s.code}` }))
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [text]);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 24, height: "100%" }}>
      <strong style={{ color: "#5b6cff", fontSize: 18 }}>◣ ChipScope</strong>
      <Menu
        mode="horizontal"
        selectedKeys={[activeKey]}
        style={{ flex: 1, borderBottom: "none" }}
        items={[
          { key: "market", label: "行情", onClick: () => nav("/") },
          { key: "watchlist", label: "自选管理", onClick: () => nav("/watchlist") },
        ]}
      />
      <AutoComplete
        style={{ width: 280 }}
        options={opts}
        value={text}
        onChange={setText}
        onSelect={(val: string) => nav(`/stock/${val}`)}
      >
        <Input.Search placeholder="搜索股票代码/名称" />
      </AutoComplete>
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/TopNav.tsx
git commit -m "feat(fe): TopNav with menu + search

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 16: SiderWatchlist 组件（常驻自选栏）

**Files:**
- Create: `frontend/src/components/SiderWatchlist.tsx`
- 可删除：`frontend/src/components/Watchlist.tsx`（旧硬编码组件，已被取代）

- [ ] **Step 1: 写组件**（API 驱动 + 实时报价红绿 + 点击切换 + inline 添加 + hover 删除）

```tsx
// frontend/src/components/SiderWatchlist.tsx
import { AutoComplete, Input, Popconfirm, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { listStocks } from "../api/stocks";
import { useWatchlist } from "../hooks/useWatchlist";
import { useQuote } from "../hooks/useRealtimeQuotes";
import type { Stock } from "../types/domain";

const { Text } = Typography;

export default function SiderWatchlist() {
  const nav = useNavigate();
  const { secucode: active } = useParams();
  const { items, add, remove } = useWatchlist();
  const [text, setText] = useState("");
  const [opts, setOpts] = useState<{ value: string; label: string }[]>([]);

  useEffect(() => {
    if (!text) {
      setOpts([]);
      return;
    }
    let cancelled = false;
    listStocks(text)
      .then((stocks: Stock[]) => {
        if (cancelled) return;
        setOpts(
          stocks.map((s) => ({ value: s.secucode, label: `${s.name} ${s.code}` }))
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [text]);

  return (
    <div style={{ padding: 12 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>
        自选股 ({items.length})
      </Text>
      <div style={{ marginTop: 8 }}>
        {items.map((w) => (
          <WatchRow
            key={w.secucode}
            secucode={w.secucode}
            name={w.name}
            active={w.secucode === active}
            onClick={() => nav(`/stock/${w.secucode}`)}
            onRemove={() => remove(w.secucode)}
          />
        ))}
      </div>
      <AutoComplete
        style={{ width: "100%", marginTop: 12 }}
        options={opts}
        value={text}
        onChange={setText}
        onSelect={async (val: string) => {
          setText("");
          await add(val);
          nav(`/stock/${val}`);
        }}
      >
        <Input.Search placeholder="+ 添加自选" />
      </AutoComplete>
    </div>
  );
}

function WatchRow({
  secucode,
  name,
  active,
  onClick,
  onRemove,
}: {
  secucode: string;
  name: string;
  active: boolean;
  onClick: () => void;
  onRemove: () => void;
}) {
  const quote = useQuote(secucode);
  const price = quote?.price;
  return (
    <div
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "6px 8px",
        borderRadius: 6,
        cursor: "pointer",
        background: active ? "#eef2ff" : "transparent",
        fontWeight: active ? 600 : 400,
      }}
      className="watch-row"
    >
      <span style={{ fontSize: 13 }}>{name}</span>
      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {price != null && (
          <span
            style={{
              fontSize: 12,
              fontFamily: "ui-monospace, monospace",
              color: "#374151",
            }}
          >
            {price.toFixed(2)}
          </span>
        )}
        <Popconfirm
          title="移出自选？"
          onConfirm={onRemove}
          okText="移出"
          cancelText="取消"
        >
          <span
            onClick={(e) => e.stopPropagation()}
            style={{ display: "none", color: "#9ca3af", cursor: "pointer" }}
            className="watch-row-del"
          >
            ×
          </span>
        </Popconfirm>
      </span>
    </div>
  );
}
```

- [ ] **Step 2: 加 hover 删除样式** — 在 `frontend/src/index.css` 末尾加：

```css
.watch-row:hover .watch-row-del {
  display: inline !important;
}
```

- [ ] **Step 3: 删除旧组件**

```bash
rm frontend/src/components/Watchlist.tsx
```

> 若有其他文件仍 import 旧 `Watchlist`，搜索并改指向 `SiderWatchlist`（StockDetail 已在 Task 14 移除该 import）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/SiderWatchlist.tsx frontend/src/index.css
git rm frontend/src/components/Watchlist.tsx
git commit -m "feat(fe): SiderWatchlist with realtime + quick add/remove

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 17: WatchlistPage 配置页（搜索 + dnd-kit 拖拽表格 + 删除）

**Files:**
- Create: `frontend/src/pages/WatchlistPage.tsx`

- [ ] **Step 1: 写配置页**

```tsx
// frontend/src/pages/WatchlistPage.tsx
import {
  AutoComplete,
  Button,
  Input,
  Popconfirm,
  Space,
  Spin,
  Table,
  Typography,
} from "antd";
import {
  closestCenter,
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useEffect, useState } from "react";
import { listStocks } from "../api/stocks";
import { useWatchlist } from "../hooks/useWatchlist";
import { useQuote } from "../hooks/useRealtimeQuotes";
import type { Stock, WatchlistItem } from "../types/domain";

const { Title, Text } = Typography;

export default function WatchlistPage() {
  const { items, loading, add, remove, reorder } = useWatchlist();
  const [text, setText] = useState("");
  const [opts, setOpts] = useState<{ value: string; label: string }[]>([]);

  useEffect(() => {
    if (!text) {
      setOpts([]);
      return;
    }
    let cancelled = false;
    listStocks(text)
      .then((stocks: Stock[]) => {
        if (cancelled) return;
        setOpts(
          stocks.map((s) => ({
            value: s.secucode,
            label: `${s.code} ${s.name} · ${s.industry ?? ""}`,
          }))
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [text]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  );

  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const ids = items.map((i) => i.secucode);
    const from = ids.indexOf(active.id as string);
    const to = ids.indexOf(over.id as string);
    reorder(arrayMove(ids, from, to));
  };

  return (
    <div style={{ maxWidth: 900 }}>
      <Title level={4} style={{ marginTop: 0 }}>
        自选管理
      </Title>
      <AutoComplete
        style={{ width: 360, marginBottom: 16 }}
        options={opts}
        value={text}
        onChange={setText}
        onSelect={async (val: string) => {
          setText("");
          await add(val);
        }}
      >
        <Input.Search placeholder="搜索股票代码/名称添加" />
      </AutoComplete>

      {loading ? (
        <Spin />
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={onDragEnd}
        >
          <SortableContext
            items={items.map((i) => i.secucode)}
            strategy={verticalListSortingStrategy}
          >
            <Table<WatchlistItem>
              rowKey="secucode"
              dataSource={items}
              pagination={false}
              components={{ body: { row: SortableRow } }}
              columns={[
                {
                  title: "代码",
                  dataIndex: "code",
                  width: 90,
                  render: (_: unknown, r: WatchlistItem) => (
                    <Text strong>{r.code}</Text>
                  ),
                },
                { title: "名称", dataIndex: "name" },
                {
                  title: "行业",
                  dataIndex: "industry",
                  width: 120,
                  render: (v: string | null) => (
                    <Text type="secondary">{v ?? "—"}</Text>
                  ),
                },
                {
                  title: "现价",
                  width: 90,
                  render: (_: unknown, r: WatchlistItem) => <PriceCell secucode={r.secucode} />,
                },
                {
                  title: "操作",
                  width: 80,
                  render: (_: unknown, r: WatchlistItem) => (
                    <Popconfirm
                      title={`移出 ${r.name}？`}
                      onConfirm={() => remove(r.secucode)}
                      okText="移出"
                      cancelText="取消"
                    >
                      <Button type="link" danger size="small">
                        删除
                      </Button>
                    </Popconfirm>
                  ),
                },
              ]}
            />
          </SortableContext>
        </DndContext>
      )}
      <Space style={{ marginTop: 16 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          拖动行调整顺序 · 增删即时同步到行情监控
        </Text>
      </Space>
    </div>
  );
}

function PriceCell({ secucode }: { secucode: string }) {
  const quote = useQuote(secucode);
  if (!quote || quote.price == null) {
    return <Text type="secondary">—</Text>;
  }
  return (
    <Text style={{ fontFamily: "ui-monospace, monospace" }}>
      {quote.price.toFixed(2)}
    </Text>
  );
}

function SortableRow(props: React.HTMLAttributes<HTMLTableRowElement> & { "data-row-key"?: string }) {
  const id = props["data-row-key"] as string | undefined;
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: id ?? "", disabled: !id });
  return (
    <tr
      {...props}
      ref={setNodeRef}
      style={{
        ...props.style,
        transform: CSS.Transform.toString(transform),
        transition,
        cursor: isDragging ? "grabbing" : "pointer",
        background: isDragging ? "#f0f5ff" : props.style?.background,
      }}
      {...attributes}
      {...listeners}
    />
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/pages/WatchlistPage.tsx
git commit -m "feat(fe): WatchlistPage with dnd-kit sortable table

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 阶段六：视觉主题（B 风格）

### Task 18: AntD theme token + RealtimeProvider 挂载

**Files:**
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: 用下面内容替换 `frontend/src/main.tsx`**

```tsx
// frontend/src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { RealtimeProvider } from "./hooks/useRealtimeQuotes";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#5b6cff",
          colorBgLayout: "#f6f7f9",
          borderRadius: 8,
          fontFamily:
            "system-ui, 'Segoe UI', Roboto, sans-serif",
        },
        components: {
          Layout: { headerBg: "#ffffff", siderBg: "#ffffff" },
          Menu: { itemSelectedBg: "#eef2ff", itemSelectedColor: "#5b6cff" },
          Table: { headerBg: "#fafafa" },
        },
        algorithm: theme.defaultAlgorithm,
      }}
    >
      <BrowserRouter>
        <RealtimeProvider>
          <App />
        </RealtimeProvider>
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>
);
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/main.tsx
git commit -m "feat(fe): AntD theme tokens (B style) + RealtimeProvider

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 19: index.css 更新为 B 风格

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: 替换 `:root` 的 CSS 变量与 `#root` 宽度** — 把 `:root { ... }` 块内的这几个变量改为：

```css
  --text: #374151;
  --text-h: #111827;
  --bg: #f6f7f9;
  --border: #e5e7eb;
  --code-bg: #f3f4f6;
  --accent: #5b6cff;
  --accent-bg: rgba(91, 108, 255, 0.1);
  --accent-border: rgba(91, 108, 255, 0.5);
```

- [ ] **Step 2: 暗色 accent 改为靛蓝亮色** — `@media (prefers-color-scheme: dark)` 块内：

```css
    --accent: #818cf8;
    --accent-bg: rgba(129, 140, 248, 0.15);
    --accent-border: rgba(129, 140, 248, 0.5);
```

- [ ] **Step 3: 放宽 `#root` 固定宽度** — 把 `#root { width: 1126px; ... }` 改为全宽自适应：

```css
#root {
  width: 100%;
  margin: 0 auto;
  min-height: 100svh;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
```

- [ ] **Step 4: 提交**

```bash
git add frontend/src/index.css
git commit -m "style(fe): B-style CSS variables + full-width root

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 阶段七：集成验证

### Task 20: 构建与测试全绿

- [ ] **Step 1: 后端全量测试**

```bash
cd backend && pytest -q
```
Expected: 全部 passed。

- [ ] **Step 2: 前端 lint + 构建**

```bash
cd frontend && npm run lint && npm run build
```
Expected: lint 无 error；`tsc -b && vite build` 成功。

- [ ] **Step 3: 前端单测**

```bash
cd frontend && npx vitest run
```
Expected: 全部 passed（含新增 useWatchlist、useRealtimeQuotes）。

- [ ] **Step 4: 修复任何回归**（如有），再次运行直到全绿。本步不单独提交（修复随对应 task 提交）。

---

### Task 21: 端到端冒烟（手动）

- [ ] **Step 1: 启动依赖与后端**

```bash
docker compose up -d
cd backend && alembic upgrade head && uvicorn app.main:app --reload --port 8001
```
Expected: 启动正常，migration 到 0002。

- [ ] **Step 2: seed 自选股** — 启动 scheduler（或调 API 手动添加）：

```bash
cd backend && python -m app.scheduler   # 会触发 seed_watchlist_if_empty
```
确认日志无报错；查库 `SELECT secucode, sort_order FROM watchlist ORDER BY sort_order;` 有 5 条种子。

- [ ] **Step 3: 启动前端**

```bash
cd frontend && npm run dev
```
打开 http://localhost:5173 ，验证：
- 顶部导航（行情/自选管理）可切换
- 左侧自选栏显示 5 只种子股，点击切换详情页
- 进入「自选管理」页，表格显示 5 只，可搜索添加新股票、删除、拖拽排序
- 增删后侧栏实时同步；scheduler 运行时（盘中）现价/涨跌实时刷新

- [ ] **Step 4: 记录结果** — 在 plan 末尾或 PR 描述里勾选验证项；如有问题回到对应 task 修复。

---

## Self-Review 已完成项

- ✅ spec 每节均有对应 task：信息架构(Task 14)、视觉系统(Task 18/19)、后端模型/API/scheduler(Task 1-8)、前端组件/hooks/WS(Task 9-17)、数据流(Task 8/13)、错误处理(Task 5 重复忽略/400、Task 13 重连、Task 16/17 Popconfirm)、测试(Task 5/8/12/13/20)
- ✅ 无占位符：每个 step 含可执行命令或完整代码
- ✅ 类型一致：`get_db`、`secucode` (600519.SH)、Redis `quote:{secucode}`、WS 全局消息含 `secucode`、前端 `WatchlistItem`/`RealtimeQuote` 贯穿一致
- ✅ scope：单一连贯特性，按依赖分 7 阶段 21 任务
