# 每日全市场分时行情存档（Daily Minute-Quote Archive）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每个交易日把全市场沪深 A 股当天分时数据（每只 1 行、JSONB 存 ~240 个 `{t,price,vol}` 分钟点）落库；前端按钮手动触发（异步 + 进度）+ 每日 15:30 cron 自动触发。

**Architecture:** 新增 `MinuteQuote` 表（JSONB）+ `services/minute_archive.py`（纯解析函数 + 采集主流程 + 内存状态）+ `api/archive.py`（POST 触发 / GET 状态）+ scheduler cron + 前端 `ArchivePage`。mootdx 真实方法 `client.minute(symbol)`（当天）/`client.minutes(symbol, date='YYYYMMDD')`（历史）返回 DataFrame 列 `[price, vol, volume]`，时间由交易时段行号推算。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 async / asyncpg / mootdx（pandas DataFrame）/ pytest + pytest-asyncio + respx / React 19 + Ant Design + react-router。

**Spec:** `docs/superpowers/specs/2026-06-22-daily-minute-quote-archive-design.md`

---

## 关键实测结论（写代码时遵循）

- mootdx `Quotes.factory(market='std')` 实例：
  - `client.minute(symbol)` → 当天分时，内部 = `client.minutes(symbol, date=今天)`
  - `client.minutes(symbol, date='YYYYMMDD')` → 指定历史日分时
  - `client.stocks(market=1)` 沪 / `client.stocks(market=0)` 深，返回 DataFrame 列 `[code, volunit, decimal_point, name, pre_close]`
- `minute`/`minutes` 返回 DataFrame 列 **`[price, vol, volume]`**，`vol` 与 `volume` 同值（每分钟增量成交量，手），240 行，**无时间/均价/成交额列**。
- 时间推算：行 0..119 → 09:31..11:30；行 120..239 → 13:01..15:00。
- A 股 code 前缀：沪 `{600,601,603,605,688,689}`；深 `{000,001,002,003,300,301}`。
- 项目**无 alembic 基线迁移**（`alembic/versions` 为空，现有表手动建）；`alembic/env.py` 已 import 全部 model，`target_metadata=Base.metadata`。
- `conftest.py` 用独立 engine + TRUNCATE 隔离，不建表；测试库 `chipscope_test` 的表需预建。本计划在 conftest 加 `create_all` 使新表自包含。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/app/models/minute_quote.py` | `MinuteQuote` ORM 模型 | 新建 |
| `backend/alembic/env.py` | 注册新 model 供 autogenerate | 修改（加 import） |
| `backend/alembic/versions/0001_minute_quote.py` | 建表迁移（开发库） | 新建（手写） |
| `backend/app/services/collector/tdx_client.py` | `minute_time()` + 分时解析纯函数 | 修改（加方法） |
| `backend/app/services/minute_archive.py` | A 股过滤 + 清单刷新 + upsert + 主流程 + 内存状态 | 新建 |
| `backend/app/schemas/archive.py` | `ArchiveStatusOut` 响应模型 | 新建 |
| `backend/app/api/archive.py` | POST 触发 / GET 状态 路由 | 新建 |
| `backend/app/main.py` | 注册 archive router | 修改（加 include） |
| `backend/app/scheduler.py` | 15:30 cron job | 修改（加 job + 函数） |
| `backend/tests/conftest.py` | `create_all` + TRUNCATE 加 `minute_quote` | 修改 |
| `backend/tests/test_minute_archive.py` | 解析/过滤/upsert/主流程测试 | 新建 |
| `backend/tests/test_archive_api.py` | API 触发/状态/防重入测试 | 新建 |
| `frontend/src/api/archive.ts` | archive 端点调用 | 新建 |
| `frontend/src/pages/ArchivePage.tsx` | 按钮 + 日期 + 进度页 | 新建 |
| `frontend/src/components/TopNav.tsx` | 加「数据存档」菜单项 | 修改 |
| `frontend/src/App.tsx` | 加 `/archive` 路由 | 修改 |

---

## Task 1: `MinuteQuote` 模型 + 迁移 + conftest 建表

**Files:**
- Create: `backend/app/models/minute_quote.py`
- Modify: `backend/alembic/env.py:16`（加 import）
- Create: `backend/alembic/versions/0001_minute_quote.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: 写模型**

`backend/app/models/minute_quote.py`:
```python
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MinuteQuote(Base):
    __tablename__ = "minute_quote"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    secucode: Mapped[str] = mapped_column(
        String(12), ForeignKey("stock_meta.secucode"), primary_key=True
    )
    data: Mapped[list] = mapped_column(JSONB)  # [{"t":"09:31","price":..,"vol":..}, ...]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 2: 注册到 alembic env**

`backend/alembic/env.py` 在第 16 行 `import app.models.watchlist` 之后加一行：
```python
import app.models.minute_quote  # noqa: F401
```

- [ ] **Step 3: 手写迁移（首个迁移，仅建 minute_quote）**

`backend/alembic/versions/0001_minute_quote.py`:
```python
"""add minute_quote

Revision ID: 0001_minute_quote
Revises:
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_minute_quote"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "minute_quote",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("secucode", sa.String(length=12), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["secucode"], ["stock_meta.secucode"],
            name="fk_minute_quote_secucode_stock_meta",
        ),
        sa.PrimaryKeyConstraint("trade_date", "secucode"),
    )
    op.create_index(
        "ix_minute_quote_secucode", "minute_quote", ["secucode"]
    )


def downgrade() -> None:
    op.drop_index("ix_minute_quote_secucode", table_name="minute_quote")
    op.drop_table("minute_quote")
```

- [ ] **Step 4: conftest 加 create_all + TRUNCATE 新表**

`backend/tests/conftest.py`：在 `from app.config import get_settings` 之后、`@pytest.fixture def respx_mock` 之前，加 model import；并把两个 TRUNCATE 语句的表列表加上 `minute_quote`，并在每个 TRUNCATE 前加 `run_sync(Base.metadata.create_all)`。

最终 `conftest.py` 顶部与 `db_session` fixture 改为：
```python
import os

# 测试强制连独立测试库 chipscope_test，避免每个用例的 TRUNCATE 误伤开发库 chipscope。
os.environ.setdefault(
    "CHIPSCOPE_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5433/chipscope_test",
)

import pytest
import pytest_asyncio
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.base import Base
# import 全部 model，让 Base.metadata 在 create_all 时覆盖所有表（含 minute_quote）
import app.models.stock  # noqa: F401
import app.models.kline  # noqa: F401
import app.models.holder  # noqa: F401
import app.models.flow  # noqa: F401
import app.models.chip  # noqa: F401
import app.models.watchlist  # noqa: F401
import app.models.minute_quote  # noqa: F401

_TRUNCATE_TABLES = (
    "stock_meta, daily_kline, top_holders, holder_summary, money_flow, "
    "chip_distribution, watchlist, minute_quote"
)


@pytest.fixture
def respx_mock():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(f"TRUNCATE {_TRUNCATE_TABLES} CASCADE"))
    async with SessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_TRUNCATE_TABLES} CASCADE"))
    await engine.dispose()
```

- [ ] **Step 5: 应用迁移到开发库**

Run:
```bash
cd backend && CHIPSCOPE_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/chipscope alembic upgrade head
```
Expected: `Running upgrade  -> 0001_minute_quote`（开发库建表）。测试库由 conftest create_all 自动建。

- [ ] **Step 6: 冒烟验证模型与建表（一个临时测试）**

`backend/tests/test_minute_quote_model.py`:
```python
from datetime import date

import pytest

from sqlalchemy import select

from app.models.minute_quote import MinuteQuote
from app.models.stock import StockMeta


@pytest.mark.asyncio
async def test_minute_quote_upsert_roundtrip(db_session):
    # 外键依赖：先建 stock_meta
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()

    db_session.add(MinuteQuote(
        trade_date=date(2026, 6, 22),
        secucode="600519.SH",
        data=[{"t": "09:31", "price": 1210.31, "vol": 1692}],
    ))
    await db_session.commit()

    row = (
        await db_session.execute(
            select(MinuteQuote).where(
                MinuteQuote.secucode == "600519.SH",
                MinuteQuote.trade_date == date(2026, 6, 22),
            )
        )
    ).scalar_one()
    assert row.data == [{"t": "09:31", "price": 1210.31, "vol": 1692}]
```

Run: `cd backend && pytest tests/test_minute_quote_model.py -v`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/minute_quote.py backend/alembic/env.py backend/alembic/versions/0001_minute_quote.py backend/tests/conftest.py backend/tests/test_minute_quote_model.py
git commit -m "feat(archive): MinuteQuote 模型与建表迁移"
```

---

## Task 2: TdxClient.minute_time + 分时解析纯函数

**Files:**
- Modify: `backend/app/services/collector/tdx_client.py`
- Test: `backend/tests/test_minute_parse.py`

- [ ] **Step 1: 写失败测试（纯函数解析）**

`backend/tests/test_minute_parse.py`:
```python
import pandas as pd

from app.services.collector.tdx_client import _row_to_time, _parse_minute_df


def test_row_to_time_morning_first_and_last():
    assert _row_to_time(0) == "09:31"
    assert _row_to_time(119) == "11:30"


def test_row_to_time_afternoon_first_and_last():
    assert _row_to_time(120) == "13:01"
    assert _row_to_time(239) == "15:00"


def test_parse_minute_df_basic():
    df = pd.DataFrame(
        {"price": [1210.31, 1205.41], "vol": [1692, 1370], "volume": [1692, 1370]}
    )
    points = _parse_minute_df(df)
    assert points == [
        {"t": "09:31", "price": 1210.31, "vol": 1692},
        {"t": "09:32", "price": 1205.41, "vol": 1370},
    ]


def test_parse_minute_df_empty_or_none():
    assert _parse_minute_df(None) == []
    assert _parse_minute_df(pd.DataFrame()) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_minute_parse.py -v`
Expected: FAIL（`_row_to_time`/`_parse_minute_df` 不存在）。

- [ ] **Step 3: 实现纯函数 + minute_time 方法**

`backend/app/services/collector/tdx_client.py`：在文件顶部 `import asyncio` 之后加 `from typing import Any`（若未导入）；在 `RealtimeQuote` dataclass 之后、`class TdxClient` 之前，加两个纯函数；在 `TdxClient` 内 `daily_bars` 方法之后，加 `minute_time` 方法。

新增纯函数（文件级）：
```python
def _row_to_time(i: int) -> str:
    """分时行号 → HH:MM。行 0..119 → 09:31..11:30；行 120..239 → 13:01..15:00。"""
    if i < 120:
        total = 9 * 60 + 30 + (i + 1)
    else:
        total = 13 * 60 + (i - 120 + 1)
    return f"{total // 60:02d}:{total % 60:02d}"


def _parse_minute_df(df) -> list[dict]:
    """mootdx 分时 DataFrame（列 price/vol/volume）→ [{t, price, vol}, ...]。

    mootdx 不提供时间/均价/成交额；vol 与 volume 同值取 vol。空 df 返回 []。
    """
    if df is None or len(df) == 0:
        return []
    prices = df["price"].tolist()
    vols = df["vol"].tolist()
    return [
        {"t": _row_to_time(i), "price": round(float(p), 3), "vol": int(v)}
        for i, (p, v) in enumerate(zip(prices, vols))
    ]
```

在 `TdxClient` 内（`daily_bars` 方法后、`_fetch_bars` 前）加：
```python
    async def minute_time(self, symbol: str, date: str | None = None) -> list[dict]:
        """mootdx 分时 → [{t, price, vol}, ...]（240 个分钟点）。

        date=None 取当天（client.minute）；date='YYYYMMDD' 取历史日（client.minutes）。
        """
        loop = asyncio.get_running_loop()
        if date is None:
            df = await loop.run_in_executor(self._executor, self._client.minute, symbol)
        else:
            df = await loop.run_in_executor(
                self._executor, lambda: self._client.minutes(symbol=symbol, date=date)
            )
        return _parse_minute_df(df)

    async def stocks(self, market: int):
        """mootdx 全市场股票清单 DataFrame（market=1 沪 / 0 深）。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._client.stocks, market)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_minute_parse.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/collector/tdx_client.py backend/tests/test_minute_parse.py
git commit -m "feat(archive): TdxClient.minute_time/stocks 与分时解析纯函数"
```

---

## Task 3: A 股清单过滤 + refresh_stock_universe

**Files:**
- Modify: `backend/app/services/minute_archive.py`（本任务创建该文件）
- Test: `backend/tests/test_minute_archive.py`

- [ ] **Step 1: 写失败测试（过滤纯函数 + refresh）**

`backend/tests/test_minute_archive.py`:
```python
import pandas as pd
import pytest

from app.services.minute_archive import _filter_a_shares, refresh_stock_universe
from app.services.collector.types import StockInfo


def test_filter_a_shares_keeps_a_drops_index_bond():
    df = pd.DataFrame(
        {
            "code": ["600519", "999999", "113001", "000001", "300750", "159915"],
            "name": ["贵州茅台", "上证指数", "可转债", "平安银行", "宁德时代", "ETF"],
            "volunit": [100] * 6,
            "decimal_point": [2] * 6,
            "pre_close": [0.0] * 6,
        }
    )
    sh = _filter_a_shares(df, market=1)
    assert {s.code for s in sh} == {"600519"}
    sz = _filter_a_shares(df, market=0)
    assert {s.code for s in sz} == {"000001", "300750"}


def test_filter_a_shares_empty():
    assert _filter_a_shares(None, market=1) == []
    assert _filter_a_shares(pd.DataFrame(), market=0) == []


class _FakeTdx:
    """fake TdxClient：stocks 返回预设 DataFrame。"""

    def __init__(self, sh_df, sz_df):
        self._sh = sh_df
        self._sz = sz_df
        self.calls = []

    async def stocks(self, market: int):
        self.calls.append(market)
        return self._sh if market == 1 else self._sz


@pytest.mark.asyncio
async def test_refresh_stock_universe_upserts_a_shares(db_session):
    # 准备 fake 清单：沪 1 只 A 股 + 1 指数；深 1 只 A 股 + 1 基金
    sh_df = pd.DataFrame(
        {"code": ["600519", "999999"], "name": ["贵州茅台", "上证指数"],
         "volunit": [100, 100], "decimal_point": [2, 2], "pre_close": [0.0, 0.0]}
    )
    sz_df = pd.DataFrame(
        {"code": ["000001", "159915"], "name": ["平安银行", "ETF"],
         "volunit": [100, 100], "decimal_point": [2, 2], "pre_close": [0.0, 0.0]}
    )
    from sqlalchemy import select
    from app.database import SessionLocal

    codes = await refresh_stock_universe(SessionLocal, _FakeTdx(sh_df, sz_df))
    assert set(codes) == {"600519.SH", "000001.SZ"}
    # 验证 stock_meta 已写入 2 只 A 股
    rows = (await db_session.execute(
        select(StockMeta.code).order_by(StockMeta.code)
    )).scalars().all()
    assert rows == ["000001", "600519"]
```
（顶部 `from app.models.stock import StockMeta` 一并 import）

完整顶部 import：
```python
import pandas as pd
import pytest

from sqlalchemy import select

from app.models.stock import StockMeta
from app.services.minute_archive import _filter_a_shares, refresh_stock_universe
from app.services.collector.types import StockInfo
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_minute_archive.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 minute_archive.py（过滤 + refresh 部分）**

`backend/app/services/minute_archive.py`（本任务先建文件，含过滤 + refresh；后续任务追加）：
```python
"""全市场分时行情存档：A 股清单刷新 + 分时采集 + upsert + 内存状态。"""
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.models.stock import StockMeta
from app.services.collector.tdx_client import TdxClient
from app.services.collector.types import StockInfo
from app.services.ingest import upsert_stock_meta

# A 股 code 前缀
_SH_PREFIXES = {"600", "601", "603", "605", "688", "689"}
_SZ_PREFIXES = {"000", "001", "002", "003", "300", "301"}


def _filter_a_shares(df, market: int) -> list[StockInfo]:
    """mootdx stocks() DataFrame + market → 仅沪深 A 股的 StockInfo 列表。

    market=1 沪（SH），market=0 深（SZ）。过滤掉指数/债券/基金/ETF 等。
    """
    if df is None or len(df) == 0:
        return []
    prefixes = _SH_PREFIXES if market == 1 else _SZ_PREFIXES
    suffix = "SH" if market == 1 else "SZ"
    secid_pfx = "1" if market == 1 else "0"
    out: list[StockInfo] = []
    for _, row in df.iterrows():
        code = str(row["code"]).zfill(6)
        if code[:3] in prefixes:
            out.append(StockInfo(
                secucode=f"{code}.{suffix}",
                code=code,
                name=str(row.get("name", code)),
                market=suffix,
                secid=f"{secid_pfx}.{code}",
            ))
    return out


async def refresh_stock_universe(
    session_factory: async_sessionmaker[AsyncSession], tdx: TdxClient
) -> list[str]:
    """拉沪深全市场股票清单 → 过滤 A 股 → upsert stock_meta。返回 A 股 secucode 列表。"""
    df_sh = await tdx.stocks(1)
    df_sz = await tdx.stocks(0)
    a_shares = _filter_a_shares(df_sh, 1) + _filter_a_shares(df_sz, 0)
    async with session_factory() as session:
        await upsert_stock_meta(session, a_shares)
    return [s.secucode for s in a_shares]
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_minute_archive.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/minute_archive.py backend/tests/test_minute_archive.py
git commit -m "feat(archive): A股清单过滤与全市场刷新"
```

---

## Task 4: upsert_minute_quote

**Files:**
- Modify: `backend/app/services/minute_archive.py`
- Test: `backend/tests/test_minute_archive.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_minute_archive.py` 末尾追加：
```python
@pytest.mark.asyncio
async def test_upsert_minute_quote_insert_and_idempotent(db_session):
    from datetime import date
    from app.models.minute_quote import MinuteQuote
    from app.services.minute_archive import upsert_minute_quote

    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()

    pts = [{"t": "09:31", "price": 10.0, "vol": 100}]
    n1 = await upsert_minute_quote(db_session, date(2026, 6, 22), "600519.SH", pts)
    assert n1 == 1

    pts2 = [{"t": "09:31", "price": 11.0, "vol": 200}]
    n2 = await upsert_minute_quote(db_session, date(2026, 6, 22), "600519.SH", pts2)
    assert n2 == 1  # 覆盖，不新增

    rows = (await db_session.execute(
        select(MinuteQuote).where(MinuteQuote.secucode == "600519.SH")
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].data == pts2  # 已被覆盖
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_minute_archive.py::test_upsert_minute_quote_insert_and_idempotent -v`
Expected: FAIL（`upsert_minute_quote` 未导入）。

- [ ] **Step 3: 实现 upsert_minute_quote**

在 `backend/app/services/minute_archive.py` 顶部 import 区加：
```python
from datetime import date
from sqlalchemy.dialects.postgresql import insert
from app.models.minute_quote import MinuteQuote
```
在 `refresh_stock_universe` 之后追加：
```python
async def upsert_minute_quote(
    session: AsyncSession, trade_date, secucode: str, points: list[dict]
) -> int:
    """幂等 upsert 单只分时：ON CONFLICT (trade_date, secucode) DO UPDATE data。"""
    if not points:
        return 0
    row = {"trade_date": trade_date, "secucode": secucode, "data": points}
    stmt = insert(MinuteQuote).values([row])
    stmt = stmt.on_conflict_do_update(
        index_elements=[MinuteQuote.trade_date, MinuteQuote.secucode],
        set_={"data": stmt.excluded.data},
    )
    await session.execute(stmt)
    await session.commit()
    return 1
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_minute_archive.py -v`
Expected: 5 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/minute_archive.py backend/tests/test_minute_archive.py
git commit -m "feat(archive): 幂等 upsert_minute_quote"
```

---

## Task 5: archive_minute_quotes 主流程 + 内存状态

**Files:**
- Modify: `backend/app/services/minute_archive.py`
- Test: `backend/tests/test_minute_archive.py`（追加）

- [ ] **Step 1: 追加失败测试（主流程 + on_progress + 状态）**

在 `backend/tests/test_minute_archive.py` 末尾追加：
```python
class _FakeArchiveTdx:
    """fake TdxClient：stocks 给清单；minute_time 给分时点（第 2 只抛错测 failed）。"""

    def __init__(self):
        self.minute_calls = []

    async def stocks(self, market: int):
        if market == 1:
            return pd.DataFrame({"code": ["600519"], "name": ["贵州茅台"],
                                 "volunit": [100], "decimal_point": [2], "pre_close": [0.0]})
        return pd.DataFrame({"code": ["000001", "300750"], "name": ["平安银行", "宁德时代"],
                             "volunit": [100, 100], "decimal_point": [2, 2],
                             "pre_close": [0.0, 0.0]})

    async def minute_time(self, symbol: str, date=None):
        self.minute_calls.append((symbol, date))
        if symbol == "300750":
            raise RuntimeError("boom")
        return [{"t": "09:31", "price": 10.0, "vol": 100}]


@pytest.mark.asyncio
async def test_archive_minute_quotes_main_flow(db_session):
    from datetime import date
    from app.services.minute_archive import (
        archive_minute_quotes, get_archive_status, reset_archive_state,
    )
    from app.database import SessionLocal

    reset_archive_state()
    progress = []

    def on_progress(done, total, failed):
        progress.append((done, total, failed))

    result = await archive_minute_quotes(
        SessionLocal, _FakeArchiveTdx(), date(2026, 6, 22), on_progress=on_progress
    )
    assert result == {"trade_date": "2026-06-22", "total": 3, "ok": 2, "failed": 1}
    assert progress[-1] == (3, 3, 1)  # 末次进度为完成态
    # ok 的两只落库
    from app.models.minute_quote import MinuteQuote
    rows = (await db_session.execute(
        select(MinuteQuote.secucode).order_by(MinuteQuote.secucode)
    )).scalars().all()
    assert rows == ["000001.SZ", "600519.SH"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_minute_archive.py::test_archive_minute_quotes_main_flow -v`
Expected: FAIL（`archive_minute_quotes` 等未定义）。

- [ ] **Step 3: 实现主流程 + 状态**

在 `backend/app/services/minute_archive.py` 顶部 import 区加：
```python
import time
```
在文件末尾追加：
```python
# ---- 进程内状态（单进程模式：API 与 cron 同进程可见）----
_archive_running: bool = False
_archive_status: dict | None = None


def get_archive_status() -> dict | None:
    return _archive_status


def is_archive_running() -> bool:
    return _archive_running


def set_archive_running(value: bool) -> None:
    global _archive_running
    _archive_running = value


def set_archive_status(value: dict | None) -> None:
    global _archive_status
    _archive_status = value


def reset_archive_state() -> None:
    """测试用：清理模块级状态。"""
    global _archive_running, _archive_status
    _archive_running = False
    _archive_status = None


async def archive_minute_quotes(
    session_factory: async_sessionmaker[AsyncSession],
    tdx: TdxClient,
    trade_date,
    on_progress=None,
) -> dict:
    """全市场分时采集主流程：刷新清单 → 遍历每只 → upsert；单只失败计入 failed。

    on_progress(done, total, failed) 每只调用一次。返回 {trade_date, total, ok, failed}。
    """
    secucodes = await refresh_stock_universe(session_factory, tdx)
    total = len(secucodes)
    ok = 0
    failed = 0
    today = _today_cst()
    date_arg = None if trade_date == today else trade_date.strftime("%Y%m%d")
    for i, secucode in enumerate(secucodes, 1):
        code = secucode.split(".")[0]
        try:
            points = await tdx.minute_time(code, date_arg)
            if points:
                async with session_factory() as session:
                    await upsert_minute_quote(session, trade_date, secucode, points)
                ok += 1
            else:
                failed += 1
        except Exception as e:  # 单只失败不影响其他
            print(f"[archive] {secucode} error: {e}")
            failed += 1
        if on_progress is not None:
            on_progress(i, total, failed)
    return {
        "trade_date": trade_date.strftime("%Y-%m-%d"),
        "total": total,
        "ok": ok,
        "failed": failed,
    }


def _today_cst():
    from zoneinfo import ZoneInfo
    from datetime import datetime
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_minute_archive.py -v`
Expected: 6 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/minute_archive.py backend/tests/test_minute_archive.py
git commit -m "feat(archive): 全量采集主流程与进程内状态"
```

---

## Task 6: API 路由（POST 触发 / GET 状态）+ 注册

**Files:**
- Create: `backend/app/schemas/archive.py`
- Create: `backend/app/api/archive.py`
- Modify: `backend/app/main.py:57`（加 include）
- Test: `backend/tests/test_archive_api.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_archive_api.py`:
```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.minute_archive import reset_archive_state, set_archive_status


@pytest.fixture(autouse=True)
def _clean_state():
    reset_archive_state()
    yield
    reset_archive_state()


@pytest.mark.asyncio
async def test_status_empty(monkeypatch, db_session):
    # 屏蔽后台真采集：把 _run_archive 替换为只写状态
    import app.api.archive as arch

    async def _fake_run(td):
        set_archive_status({"state": "done", "trade_date": str(td),
                            "total": 1, "ok": 1, "failed": 0})
    monkeypatch.setattr(arch, "_run_archive", _fake_run)

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as ac:
        r = await ac.get("/api/archive/minute/status")
        assert r.status_code == 200
        assert r.json() is None  # 初始无状态


@pytest.mark.asyncio
async def test_trigger_then_status_done(monkeypatch, db_session):
    import app.api.archive as arch

    async def _fake_run(td):
        set_archive_status({"state": "done", "trade_date": str(td),
                            "total": 2, "ok": 2, "failed": 0})
    monkeypatch.setattr(arch, "_run_archive", _fake_run)

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as ac:
        r = await ac.post("/api/archive/minute")
        assert r.status_code == 202
        # 给后台 task 一点时间
        import asyncio
        await asyncio.sleep(0.1)
        s = await ac.get("/api/archive/minute/status")
        assert s.status_code == 200
        body = s.json()
        assert body["state"] == "done"
        assert body["ok"] == 2


@pytest.mark.asyncio
async def test_trigger_rejects_when_running(monkeypatch, db_session):
    import app.api.archive as arch
    from app.services.minute_archive import set_archive_running

    async def _slow_run(td):
        import asyncio
        await asyncio.sleep(1.0)
    monkeypatch.setattr(arch, "_run_archive", _slow_run)
    set_archive_running(True)  # 预置为运行中

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as ac:
        r = await ac.post("/api/archive/minute")
        assert r.status_code == 409
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_archive_api.py -v`
Expected: FAIL（路由不存在）。

- [ ] **Step 3: 实现响应模型 + 路由**

`backend/app/schemas/archive.py`:
```python
from pydantic import BaseModel


class ArchiveStatusOut(BaseModel):
    state: str | None = None
    trade_date: str | None = None
    total: int = 0
    done: int = 0
    failed: int = 0
    started_at: int | None = None
    finished_at: int | None = None
    error: str | None = None


class ArchiveTriggerResponse(BaseModel):
    task_id: str
    trade_date: str
```

`backend/app/api/archive.py`:
```python
"""分时存档触发与状态查询。"""
import asyncio
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.database import SessionLocal
from app.schemas.archive import ArchiveStatusOut, ArchiveTriggerResponse
from app.services.collector.tdx_client import TdxClient
from app.services.minute_archive import (
    archive_minute_quotes,
    get_archive_status,
    is_archive_running,
    set_archive_running,
    set_archive_status,
    _today_cst,
)

router = APIRouter(prefix="/api/archive", tags=["archive"])

_background_tasks: set[asyncio.Task] = set()


async def _run_archive(trade_date: date) -> None:
    """后台采集：复用一个 TdxClient，全程更新内存状态。异常写 error。"""
    started = _now_ts()
    td_str = trade_date.strftime("%Y-%m-%d")
    set_archive_status({
        "state": "running", "trade_date": td_str,
        "total": 0, "done": 0, "failed": 0,
        "started_at": started, "finished_at": None, "error": None,
    })
    tdx = TdxClient()
    try:
        def on_progress(done, total, failed):
            set_archive_status({
                "state": "running", "trade_date": td_str,
                "total": total, "done": done, "failed": failed,
                "started_at": started, "finished_at": None, "error": None,
            })
        result = await archive_minute_quotes(
            SessionLocal, tdx, trade_date, on_progress=on_progress
        )
        set_archive_status({
            "state": "done", **result,
            "started_at": started, "finished_at": _now_ts(), "error": None,
        })
    except Exception as e:
        set_archive_status({
            "state": "error", "trade_date": td_str,
            "total": 0, "done": 0, "failed": 0,
            "started_at": started, "finished_at": _now_ts(), "error": str(e),
        })
    finally:
        tdx.close()
        set_archive_running(False)


def _now_ts() -> int:
    import time
    return int(time.time())


def _schedule_archive(trade_date: date) -> None:
    set_archive_running(True)
    task = asyncio.create_task(_run_archive(trade_date))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.post("/minute", response_model=ArchiveTriggerResponse, status_code=202)
async def trigger_minute_archive(
    date_str: str | None = Query(None, alias="date"),
):
    if is_archive_running():
        raise HTTPException(status_code=409, detail="archive task already running")
    trade_date = _parse_date(date_str) if date_str else _today_cst()
    _schedule_archive(trade_date)
    return ArchiveTriggerResponse(task_id=trade_date.strftime("%Y%m%d"),
                                  trade_date=trade_date.strftime("%Y-%m-%d"))


@router.get("/minute/status", response_model=ArchiveStatusOut | None)
async def minute_archive_status():
    return get_archive_status()


def _parse_date(s: str) -> date:
    from datetime import datetime
    return datetime.strptime(s, "%Y-%m-%d").date()
```

- [ ] **Step 4: 注册 router**

`backend/app/main.py`：在 `from app.api.watchlist import router as watchlist_router` 之后加：
```python
from app.api.archive import router as archive_router
```
在 `app.include_router(watchlist_router)` 之后加：
```python
app.include_router(archive_router)
```

- [ ] **Step 5: 运行确认通过**

Run: `cd backend && pytest tests/test_archive_api.py -v`
Expected: 3 passed。

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/archive.py backend/app/api/archive.py backend/app/main.py backend/tests/test_archive_api.py
git commit -m "feat(archive): 触发与状态查询 API"
```

---

## Task 7: scheduler 15:30 cron job

**Files:**
- Modify: `backend/app/scheduler.py`
- Test: `backend/tests/test_scheduler_archive.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_scheduler_archive.py`:
```python
import pytest

from app.scheduler import build_scheduler, daily_minute_archive


def test_build_scheduler_has_minute_archive_job():
    sched = build_scheduler()
    job_ids = [j.id for j in sched.get_jobs()]
    assert "daily_minute_archive" in job_ids
    job = next(j for j in sched.get_jobs() if j.id == "daily_minute_archive")
    # 每天 15:30 北京时间
    assert job.trigger.__class__.__name__ == "CronTrigger"
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "15"
    assert fields["minute"] == "30"


@pytest.mark.asyncio
async def test_daily_minute_archive_calls_archive(monkeypatch):
    """daily_minute_archive 应调用 archive_minute_quotes(当天)。"""
    import app.scheduler as sched_mod
    called = {}

    async def _fake_archive(session_factory, tdx, trade_date, on_progress=None):
        called["trade_date"] = trade_date

    class _FakeTdx:
        def close(self): pass

    monkeypatch.setattr(sched_mod, "archive_minute_quotes", _fake_archive)
    monkeypatch.setattr(sched_mod, "TdxClient", lambda: _FakeTdx())
    await daily_minute_archive()
    assert "trade_date" in called
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_scheduler_archive.py -v`
Expected: FAIL（`daily_minute_archive` 不存在 / job 不存在）。

- [ ] **Step 3: 实现 cron job**

`backend/app/scheduler.py`：
- 顶部 import 区，在 `from app.services.kline_chip import ingest_kline_and_chips` 之后加：
```python
from app.services.minute_archive import archive_minute_quotes
```
- 在 `daily_kline_chip()` 函数之后、`build_scheduler()` 之前加：
```python
async def daily_minute_archive() -> None:
    """15:30 增量存档全市场当天分时数据（mootdx TCP）。

    与 daily（16:00 holders/flow）错开 30 分钟，独立 TdxClient 连接。
    """
    tdx = TdxClient()
    try:
        trade_date = _today_cst()
        await archive_minute_quotes(SessionLocal, tdx, trade_date)
    finally:
        tdx.close()
```
- 在 `build_scheduler()` 内，`sched.add_job(daily_kline_chip, ...)` 之后加：
```python
    sched.add_job(
        daily_minute_archive, CronTrigger(hour=15, minute=30),
        id="daily_minute_archive",
    )
```
- 文件末尾加 `_today_cst` 辅助：
```python
def _today_cst():
    from zoneinfo import ZoneInfo
    from datetime import datetime
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_scheduler_archive.py -v`
Expected: 2 passed。再跑全量回归：
```bash
cd backend && pytest -q
```
Expected: 全绿（含原有 80 + 新增）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/scheduler.py backend/tests/test_scheduler_archive.py
git commit -m "feat(archive): 每日 15:30 全量分时存档定时任务"
```

---

## Task 8: 前端 —— 存档页 + 导航 + 路由

**Files:**
- Create: `frontend/src/api/archive.ts`
- Create: `frontend/src/pages/ArchivePage.tsx`
- Modify: `frontend/src/components/TopNav.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 写 API 封装**

`frontend/src/api/archive.ts`:
```typescript
import { apiGet, apiPost } from "./client";

export interface ArchiveStatus {
  state: "running" | "done" | "error" | null;
  trade_date: string | null;
  total: number;
  done: number;
  failed: number;
  started_at: number | null;
  finished_at: number | null;
  error: string | null;
}

export const triggerArchive = (date?: string) =>
  apiPost<{ task_id: string; trade_date: string }>(
    `/archive/minute${date ? `?date=${date}` : ""}`
  );

export const getArchiveStatus = () =>
  apiGet<ArchiveStatus | null>("/archive/minute/status");
```

- [ ] **Step 2: 写 ArchivePage**

`frontend/src/pages/ArchivePage.tsx`:
```tsx
import { Button, Card, DatePicker, message, Progress, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import {
  ArchiveStatus,
  getArchiveStatus,
  triggerArchive,
} from "../api/archive";

const { Text } = Typography;

export default function ArchivePage() {
  const [status, setStatus] = useState<ArchiveStatus | null>(null);
  const [date, setDate] = useState<dayjs.Dayjs | null>(null);
  const [loading, setLoading] = useState(false);

  // 首次加载 + 运行中轮询
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    getArchiveStatus().then(setStatus);
    timer = setInterval(async () => {
      try {
        setStatus(await getArchiveStatus());
      } catch {
        /* ignore */
      }
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  const trigger = async () => {
    setLoading(true);
    try {
      const dateStr = date ? date.format("YYYY-MM-DD") : undefined;
      await triggerArchive(dateStr);
      message.success("已开始存档，请关注进度");
    } catch (e: any) {
      const msg = String(e?.message || e);
      if (msg.includes("409")) {
        message.warning("已有存档任务在运行");
      } else {
        message.error(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  const running = status?.state === "running";
  const pct =
    status && status.total > 0
      ? Math.round(((status.done + status.failed) / status.total) * 100)
      : 0;

  return (
    <Card title="分时行情存档" style={{ maxWidth: 720 }}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <div>
          <Text type="secondary">
            把全市场沪深 A 股当天分时数据（每只 ~240 个分钟点）落库。
            默认当天，可选历史日（仅最近若干交易日可补）。
          </Text>
        </div>
        <Space>
          <DatePicker
            value={date}
            onChange={setDate}
            placeholder="留空=当天"
            allowClear
          />
          <Button type="primary" loading={loading} onClick={trigger} disabled={running}>
            {running ? "存档中…" : "开始存档"}
          </Button>
        </Space>
        {status && status.state && (
          <div>
            <Space>
              <Tag color={status.state === "done" ? "green" : status.state === "error" ? "red" : "blue"}>
                {status.state}
              </Tag>
              <Text>交易日：{status.trade_date ?? "-"}</Text>
            </Space>
            <Progress percent={pct} status={status.state === "error" ? "exception" : running ? "active" : "normal"} />
            <Space size="large">
              <Text>总计 {status.total}</Text>
              <Text type="success">成功 {status.done}</Text>
              <Text type="danger">失败 {status.failed}</Text>
            </Space>
            {status.error && <Text type="danger">错误：{status.error}</Text>}
          </div>
        )}
      </Space>
    </Card>
  );
}
```

- [ ] **Step 3: TopNav 加菜单项**

`frontend/src/components/TopNav.tsx`：把 `activeKey` 计算改为支持 archive，并在 Menu items 加一项。

把：
```tsx
  const activeKey = loc.pathname.startsWith("/watchlist") ? "watchlist" : "market";
```
改为：
```tsx
  const activeKey = loc.pathname.startsWith("/watchlist")
    ? "watchlist"
    : loc.pathname.startsWith("/archive")
    ? "archive"
    : "market";
```
把 Menu items 数组改为：
```tsx
          items={[
            { key: "market", label: "行情", onClick: () => nav("/") },
            { key: "watchlist", label: "自选管理", onClick: () => nav("/watchlist") },
            { key: "archive", label: "数据存档", onClick: () => nav("/archive") },
          ]}
```

- [ ] **Step 4: App 加路由**

`frontend/src/App.tsx`：在 `import WatchlistPage` 之后加：
```tsx
import ArchivePage from "./pages/ArchivePage";
```
在 `<Route path="/watchlist" element={<WatchlistPage />} />` 之后加：
```tsx
        <Route path="/archive" element={<ArchivePage />} />
```

- [ ] **Step 5: 确认 dayjs 可用**

`dayjs` 是 antd DatePicker 的对等依赖（antd v5 依赖 dayjs）。验证：
Run: `cd frontend && npm run build`
Expected: 构建成功（无 TS / 导入错误）。

- [ ] **Step 6: 手测（可选）**

```bash
cd backend && uvicorn app.main:app --port 8001 &
cd frontend && npm run dev
```
浏览器打开 `/archive`，点「开始存档」，观察进度条推进、state 变 done。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/archive.ts frontend/src/pages/ArchivePage.tsx frontend/src/components/TopNav.tsx frontend/src/App.tsx
git commit -m "feat(archive): 前端数据存档页与导航入口"
```

---

## 收尾

- [ ] 全量后端测试：`cd backend && pytest -q`（全绿）
- [ ] 前端构建：`cd frontend && npm run build`（成功）
- [ ] 更新 `CLAUDE.md` Module Map（加 archive 相关模块）—— 可选
