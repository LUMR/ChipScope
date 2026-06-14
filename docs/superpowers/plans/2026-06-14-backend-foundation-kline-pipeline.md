# ChipScope 后端地基 + 日K采集链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 ChipScope 后端骨架（FastAPI + SQLAlchemy async + TimescaleDB），打通"东方财富日K前复权采集 → 入库（含换手率/VWAP）→ REST 查询"的核心数据链路，产出可独立运行、可测试的软件。

**Architecture:** FastAPI 异步 API 层 + SQLAlchemy 2.0 async/asyncpg + TimescaleDB 超表。采集层用 `httpx` 异步请求东方财富 HTTP API（日K前复权 `fqt=1`、全市场列表）。日K超表用 TimescaleDB hypertable。本 plan 不涉及 mootdx 实时行情、股东/资金流、筹码引擎、前端——这些是后续 plan。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2.0 (async) + asyncpg、Alembic、pydantic-settings、httpx、TimescaleDB (pg15)、Redis（占位，本 plan 暂不深度使用）、pytest + pytest-asyncio + respx（httpx mock）。

**已确认的关键设计决策（来自审查对齐）：**
1. 日K前复权走东方财富 `push2his`（`fqt=1`），不通达信——复权可靠优先。
2. 换手率直接取东财日K `f61` 字段（P0-1 在此方案下自动解决，无需自算流通股本）。
3. 后端采集与未来计算走独立 worker 进程，API 服务只读 DB——本 plan 先实现可被手动调用的采集服务函数，调度框架留后续 plan。
4. 幂等写入：日K用 `ON CONFLICT (secucode, ts) DO UPDATE`。
5. 时区：DB 用 TIMESTAMPTZ（UTC 存储），交易日按北京时区 (`Asia/Shanghai`) 归一化到该日 15:30 作为 ts。

---

## File Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app 装配 + 路由挂载
│   ├── config.py                  # pydantic-settings 配置
│   ├── database.py                # async engine + session factory
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py                # DeclarativeBase
│   │   ├── stock.py               # StockMeta 模型
│   │   └── kline.py               # DailyKline 模型
│   ├── schemas/                   # Pydantic 响应模型
│   │   ├── __init__.py
│   │   ├── stock.py
│   │   └── kline.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                # 依赖注入（DB session）
│   │   └── stocks.py              # 股票列表 + K线查询路由
│   ├── services/
│   │   ├── __init__.py
│   │   ├── collector/
│   │   │   ├── __init__.py
│   │   │   ├── eastmoney.py       # 东财 HTTP 客户端：全市场列表 + 日K前复权
│   │   │   └── types.py           # 采集层数据类型 (StockInfo, KlineBar)
│   │   └── ingest.py              # 采集编排：写入 DB（upsert）
│   └── utils/
│       ├── __init__.py
│       └── time.py                # 北京交易日归一化
├── alembic/
│   ├── env.py                     # 异步 alembic 配置
│   ├── script.py.mako
│   └── versions/
│       └── 0001_init.py           # 建表 + hypertable
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # pytest fixtures（test DB、httpx mock）
│   ├── test_eastmoney.py
│   ├── test_ingest.py
│   └── test_api_stocks.py
├── alembic.ini
├── requirements.txt
└── pytest.ini
```

**职责边界：**
- `collector/eastmoney.py`：只管"请求 + 解析"，返回纯数据类型，不碰 DB。可独立单测。
- `services/ingest.py`：只管"数据落库"，接收已解析数据，做 upsert。可单测。
- `api/`：只管 HTTP，调 ingest/查询，无业务逻辑。
- 分层后每层可独立 TDD。

---

## Task 1: 初始化项目结构、依赖与 git

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py` (空)
- Create: `backend/app/models/__init__.py` (空)
- Create: `backend/app/api/__init__.py` (空)
- Create: `backend/app/services/__init__.py` (空)
- Create: `backend/app/services/collector/__init__.py` (空)
- Create: `backend/app/schemas/__init__.py` (空)
- Create: `backend/app/utils/__init__.py` (空)
- Create: `backend/tests/__init__.py` (空)
- Create: `backend/pytest.ini`

- [ ] **Step 1: git init（仓库尚不存在）**

Run:
```bash
cd /d/Codes/ChipScope
git init
git add astock-analysis-design.md
git commit -m "docs: add ChipScope design doc v1.1"
```

- [ ] **Step 2: 创建 requirements.txt**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
alembic==1.14.0
pydantic-settings==2.7.0
httpx==0.28.1
redis==5.2.1
numpy==2.2.1
python-dateutil==2.9.0

# dev / test
pytest==8.3.4
pytest-asyncio==0.25.0
respx==0.22.0
anyio==4.7.0
```

- [ ] **Step 3: 创建所有空 `__init__.py`**

每个文件内容为空字符串 `""`。

- [ ] **Step 4: 创建 pytest.ini**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 5: 创建 venv 并安装**

Run:
```bash
cd /d/Codes/ChipScope/backend
python -m venv .venv
.venv/Scripts/python -m pip install -U pip
.venv/Scripts/pip install -r requirements.txt
```
Expected: 所有包安装成功。

- [ ] **Step 6: Commit**

```bash
cd /d/Codes/ChipScope
printf '.venv/\n__pycache__/\n*.pyc\n.pytest_cache/\n' > .gitignore
git add .gitignore backend
git commit -m "chore: scaffold backend project with dependencies"
```

---

## Task 2: 配置管理 (config.py)

**Files:**
- Create: `backend/app/config.py`

- [ ] **Step 1: 写 config.py**

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHIPSCOPE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/chipscope"
    redis_url: str = "redis://localhost:6379/0"

    # 东方财富请求节流：两次请求间最小间隔（秒）
    eastmoney_min_interval: float = 0.5
    eastmoney_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 2: 验证可导入**

Run:
```bash
cd /d/Codes/ChipScope/backend
.venv/Scripts/python -c "from app.config import get_settings; print(get_settings().database_url)"
```
Expected: 打印默认 database_url。

- [ ] **Step 3: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/app/config.py
git commit -m "feat: add pydantic-settings config"
```

---

## Task 3: Docker Compose (TimescaleDB + Redis)

**Files:**
- Create: `docker-compose.yml`
- Create: `backend/.env`

- [ ] **Step 1: 写 docker-compose.yml**

```yaml
services:
  db:
    image: timescale/timescaledb:latest-pg15
    environment:
      POSTGRES_DB: chipscope
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d chipscope"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  pgdata:
```

- [ ] **Step 2: 写 backend/.env（本地开发连接到 docker 暴露的端口）**

```
CHIPSCOPE_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/chipscope
CHIPSCOPE_REDIS_URL=redis://localhost:6379/0
```

- [ ] **Step 3: 启动并验证**

Run:
```bash
cd /d/Codes/ChipScope
docker compose up -d
docker compose exec db psql -U postgres -d chipscope -c "SELECT extversion FROM pg_extension WHERE extname='timescaledb';"
```
Expected: TimescaleDB 扩展需手动启用（下一 task 迁移里做）。此处仅验证容器健康、psql 可连。若报扩展不存在属正常。

补充启用扩展（迁移也会做，此处先确保 SQL 可跑）：
```bash
docker compose exec db psql -U postgres -d chipscope -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
```
Expected: `CREATE EXTENSION`。

- [ ] **Step 4: 更新 .gitignore，提交**

把 `.env` 加入 `.gitignore`（不提交密钥/本地配置）。
```bash
cd /d/Codes/ChipScope
printf 'backend/.env\n' >> .gitignore
git add .gitignore docker-compose.yml
git commit -m "infra: add docker-compose for timescaledb + redis"
```

---

## Task 4: 数据库连接层 (database.py)

**Files:**
- Create: `backend/app/models/base.py`
- Create: `backend/app/database.py`

- [ ] **Step 1: 写 base.py（DeclarativeBase + 命名约定）**

```python
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
```

- [ ] **Step 2: 写 database.py**

```python
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.config import get_settings


def create_engine():
    return create_async_engine(get_settings().database_url, pool_pre_ping=True, future=True)


engine = create_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
```

- [ ] **Step 3: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/app/models/base.py backend/app/database.py
git commit -m "feat: add async db engine and session factory"
```

---

## Task 5: 数据模型 (stock_meta, daily_kline)

**Files:**
- Create: `backend/app/models/stock.py`
- Create: `backend/app/models/kline.py`

- [ ] **Step 1: 写 stock.py**

```python
from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class StockMeta(Base):
    __tablename__ = "stock_meta"

    secucode: Mapped[str] = mapped_column(String(12), primary_key=True)  # 600519.SH
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    market: Mapped[str] = mapped_column(String(4), nullable=False)  # SH / SZ / BJ
    secid: Mapped[str] = mapped_column(String(12), nullable=False)  # 1.600519
    list_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 2: 写 kline.py**

```python
from datetime import datetime
from sqlalchemy import String, DateTime, Numeric, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class DailyKline(Base):
    __tablename__ = "daily_kline"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    secucode: Mapped[str] = mapped_column(
        String(12), ForeignKey("stock_meta.secucode"), primary_key=True
    )
    open: Mapped[float] = mapped_column(Numeric(10, 3))
    close: Mapped[float] = mapped_column(Numeric(10, 3))
    high: Mapped[float] = mapped_column(Numeric(10, 3))
    low: Mapped[float] = mapped_column(Numeric(10, 3))
    volume: Mapped[int] = mapped_column(BigInteger)           # 成交量(手)
    amount: Mapped[float] = mapped_column(Numeric(18, 2))     # 成交额(元)
    turnover_rate: Mapped[float] = mapped_column(Numeric(8, 4))  # 换手率% (东财 f61)
    pct_change: Mapped[float] = mapped_column(Numeric(8, 4))     # 涨跌幅% (东财 f59)
    vwap: Mapped[float] = mapped_column(Numeric(10, 3))          # 均价 = amount/vol/100
```

- [ ] **Step 3: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/app/models/stock.py backend/app/models/kline.py
git commit -m "feat: add StockMeta and DailyKline models"
```

---

## Task 6: Alembic 迁移（建表 + hypertable）

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_init.py`

- [ ] **Step 1: alembic.ini（关键节选）**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
qualname =
[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine
[logger_alembic]
level = INFO
handlers =
qualname = alembic
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 2: alembic/env.py（异步 + 读取 config 的 database_url）**

```python
import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from app.config import get_settings
from app.models.base import Base
import app.models.stock  # noqa: F401  注册模型
import app.models.kline  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: script.py.mako（alembic 标准模板）**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: 手写初始迁移 0001_init.py（建表 + TimescaleDB 扩展 + 超表）**

```python
"""init schema with stock_meta and daily_kline hypertable

Revision ID: 0001
Revises:
Create Date: 2026-06-14
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

    op.create_table(
        "stock_meta",
        sa.Column("secucode", sa.String(12), primary_key=True),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("market", sa.String(4), nullable=False),
        sa.Column("secid", sa.String(12), nullable=False),
        sa.Column("list_date", sa.Date(), nullable=True),
        sa.Column("industry", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "daily_kline",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("open", sa.Numeric(10, 3)),
        sa.Column("close", sa.Numeric(10, 3)),
        sa.Column("high", sa.Numeric(10, 3)),
        sa.Column("low", sa.Numeric(10, 3)),
        sa.Column("volume", sa.BigInteger()),
        sa.Column("amount", sa.Numeric(18, 2)),
        sa.Column("turnover_rate", sa.Numeric(8, 4)),
        sa.Column("pct_change", sa.Numeric(8, 4)),
        sa.Column("vwap", sa.Numeric(10, 3)),
        sa.ForeignKeyConstraint(["secucode"], ["stock_meta.secucode"]),
        sa.PrimaryKeyConstraint("secucode", "ts"),
    )
    # TimescaleDB 超表：按月分块
    op.execute(
        "SELECT create_hypertable('daily_kline', 'ts', "
        "chunk_time_interval => INTERVAL '30 days');"
    )
    op.create_index(
        "ix_daily_kline_ts", "daily_kline", ["ts"], postgresql_using="btree"
    )


def downgrade() -> None:
    op.drop_table("daily_kline")
    op.drop_table("stock_meta")
```

- [ ] **Step 5: 跑迁移并验证**

Run:
```bash
cd /d/Codes/ChipScope/backend
.venv/Scripts/alembic upgrade head
.venv/Scripts/python -c "
import asyncio
from sqlalchemy import text
from app.database import engine
async def main():
    async with engine.connect() as c:
        r = await c.execute(text(\"SELECT hypertable_name FROM timescaledb_information.hypertables\"))
        print(r.fetchall())
asyncio.run(main())
"
```
Expected: `[('daily_kline',)]`，确认超表已建。

- [ ] **Step 6: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/alembic.ini backend/alembic backend/requirements.txt
git commit -m "feat(db): alembic init migration with daily_kline hypertable"
```

---

## Task 7: 东财全市场列表客户端 + 测试

**Files:**
- Create: `backend/app/services/collector/types.py`
- Create: `backend/app/services/collector/eastmoney.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_eastmoney.py`

**东财接口说明（已确认）：**
- 列表：`GET https://push2.eastmoney.com/api/qt/clist/get`
  - `fs=m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23` = 深主板+创业板+沪主板+科创板
  - `fields=f12,f13,f14` → f12=代码, f13=市场(1=沪→SH, 0=深→SZ), f14=名称
  - 返回 `data.list: [{f12, f13, f14}, ...]`
- 日K：`GET https://push2his.eastmoney.com/api/qt/stock/kline/get`
  - `secid=1.600519&klt=101&fqt=1&beg=20200101&end=20261231`
  - `fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61`
  - klines 每行：`日期,开,收,高,低,成交量(手),成交额,振幅,涨跌幅,涨跌额,换手率`

- [ ] **Step 1: 写 types.py**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class StockInfo:
    secucode: str   # 600519.SH
    code: str       # 600519
    name: str
    market: str     # SH / SZ / BJ
    secid: str      # 1.600519


@dataclass(frozen=True)
class KlineBar:
    date: str           # "2026-06-13"
    open: float
    close: float
    high: float
    low: float
    volume: int         # 手
    amount: float       # 元
    pct_change: float   # %
    turnover_rate: float  # %
    vwap: float         # 均价 = amount/vol/100
```

- [ ] **Step 2: 写 eastmoney.py 的 list_stocks + 市场映射辅助**

```python
import asyncio
from collections.abc import AsyncIterator
import httpx
from app.config import get_settings
from app.services.collector.types import StockInfo, KlineBar

_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

# 东财 fs 片段：覆盖沪深主板/创业板/科创板（北交所 m:0 t:81 留待后续）
_A_SHARE_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"


def _market_of(f13: int) -> str:
    # f13: 1=沪, 0=深
    return "SH" if f13 == 1 else "SZ"


def _secid_of(f13: int, code: str) -> str:
    return f"{f13}.{code}"


def _secucode_of(f13: int, code: str) -> str:
    return f"{code}.{_market_of(f13)}"


class EastMoneyClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        headers = {"User-Agent": settings.eastmoney_user_agent, "Referer": "https://quote.eastmoney.com/"}
        self._client = client or httpx.AsyncClient(headers=headers, timeout=10.0)
        self._min_interval = settings.eastmoney_min_interval
        self._last_call = 0.0

    async def _throttle(self) -> None:
        # 最小请求间隔，避免触发反爬
        loop = asyncio.get_event_loop()
        now = loop.time()
        wait = self._min_interval - (now - self._last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = loop.time()

    async def list_stocks(self) -> list[StockInfo]:
        await self._throttle()
        params = {
            "pn": 1, "pz": 10000, "po": 1, "np": 1,
            "fltt": 2, "invt": 2, "fid": "f3",
            "fs": _A_SHARE_FS,
            "fields": "f12,f13,f14",
        }
        resp = await self._client.get(_LIST_URL, params=params)
        resp.raise_for_status()
        rows = resp.json().get("data", {}).get("list", []) or []
        result = []
        for r in rows:
            f13 = int(r["f13"])
            code = str(r["f12"])
            result.append(StockInfo(
                secucode=_secucode_of(f13, code),
                code=code,
                name=str(r["f14"]),
                market=_market_of(f13),
                secid=_secid_of(f13, code),
            ))
        return result

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 3: 写 conftest.py**

```python
import pytest
import respx
import httpx


@pytest.fixture
def respx_mock():
    with respx.mock(assert_all_called=False) as m:
        yield m
```

- [ ] **Step 4: 写测试 test_list_stocks（先让它失败）**

```python
import httpx
import respx
import pytest
from app.services.collector.eastmoney import EastMoneyClient


@pytest.mark.asyncio
async def test_list_stocks_parses_market_and_secid(respx_mock):
    respx_mock.get("https://push2.eastmoney.com/api/qt/clist/get").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "list": [
                    {"f12": "600519", "f13": 1, "f14": "贵州茅台"},
                    {"f12": "000001", "f13": 0, "f14": "平安银行"},
                ]
            }
        })
    )
    async with EastMoneyClient() as em:
        stocks = await em.list_stocks()
    assert stocks[0].secucode == "600519.SH"
    assert stocks[0].secid == "1.600519"
    assert stocks[0].market == "SH"
    assert stocks[1].secucode == "000001.SZ"
    assert stocks[1].secid == "0.000001"


@pytest.mark.asyncio
async def test_list_stocks_empty_when_no_data(respx_mock):
    respx_mock.get("https://push2.eastmoney.com/api/qt/clist/get").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with EastMoneyClient() as em:
        stocks = await em.list_stocks()
    assert stocks == []
```

- [ ] **Step 5: 运行测试**

Run:
```bash
cd /d/Codes/ChipScope/backend
.venv/Scripts/python -m pytest tests/test_eastmoney.py -v
```
Expected: 2 passed。

- [ ] **Step 6: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/app/services/collector backend/tests
git commit -m "feat(collector): eastmoney stock list client with tests"
```

---

## Task 8: stock_meta 初始化服务 + 测试

**Files:**
- Create: `backend/app/services/ingest.py`
- Create: `backend/tests/test_ingest.py`

- [ ] **Step 1: 写 ingest.py 的 upsert_stock_meta（先用 sqlalchemy.dialects.postgresql.insert 做 upsert）**

```python
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.stock import StockMeta
from app.models.kline import DailyKline
from app.services.collector.types import StockInfo, KlineBar


async def upsert_stock_meta(session: AsyncSession, stocks: list[StockInfo]) -> int:
    if not stocks:
        return 0
    rows = [
        {"secucode": s.secucode, "code": s.code, "name": s.name,
         "market": s.market, "secid": s.secid}
        for s in stocks
    ]
    stmt = insert(StockMeta).values(rows)
    first = rows[0]
    update_cols = {c: stmt.excluded[c] for c in first if c != "secucode"}
    stmt = stmt.on_conflict_do_update(index_elements=[StockMeta.secucode], set_=update_cols)
    await session.execute(stmt)
    await session.commit()
    return len(rows)
```

- [ ] **Step 2: 写测试（用 SQLite 异步内存库做隔离单测；upsert 语义在 SQLite 也成立）**

```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models.base import Base
from app.models.stock import StockMeta
from app.services.ingest import upsert_stock_meta
from app.services.collector.types import StockInfo


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_stock_meta_inserts_then_updates(session):
    stocks = [StockInfo("600519.SH", "600519", "贵州茅台", "SH", "1.600519")]
    n = await upsert_stock_meta(session, stocks)
    assert n == 1
    rows = (await session.execute(__import__("sqlalchemy").select(StockMeta))).scalars().all()
    assert len(rows) == 1 and rows[0].name == "贵州茅台"

    # 改名再 upsert，应更新而非新增
    stocks[0] = StockInfo("600519.SH", "600519", "茅台股份", "SH", "1.600519")
    await upsert_stock_meta(session, stocks)
    rows = (await session.execute(__import__("sqlalchemy").select(StockMeta))).scalars().all()
    assert len(rows) == 1 and rows[0].name == "茅台股份"
```

> **注意：** 测试用 SQLite，需在 requirements-dev 加 `aiosqlite`。把它加入 requirements.txt 的 dev 段（或单独 requirements-dev.txt）。在 Task 1 的 requirements.txt 末尾补 `aiosqlite==0.20.0`（若已 commit 则在此 task 内追加并 amend/新 commit）。

- [ ] **Step 3: 补 aiosqlite 依赖**

编辑 `backend/requirements.txt`，在 dev 段追加：
```
aiosqlite==0.20.0
```
Run:
```bash
cd /d/Codes/ChipScope/backend
.venv/Scripts/pip install aiosqlite==0.20.0
```

- [ ] **Step 4: 运行测试**

Run:
```bash
cd /d/Codes/ChipScope/backend
.venv/Scripts/python -m pytest tests/test_ingest.py -v
```
Expected: 1 passed。

- [ ] **Step 5: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/app/services/ingest.py backend/tests/test_ingest.py backend/requirements.txt
git commit -m "feat(ingest): stock_meta upsert service with tests"
```

---

## Task 9: 东财日K客户端（前复权）+ 测试

**Files:**
- Modify: `backend/app/services/collector/eastmoney.py`（追加 fetch_daily_kline）
- Modify: `backend/tests/test_eastmoney.py`（追加测试）

- [ ] **Step 1: 在 eastmoney.py 的 EastMoneyClient 类内追加 fetch_daily_kline 方法**

```python
    async def fetch_daily_kline(self, secid: str, beg: str, end: str) -> list[KlineBar]:
        """拉取前复权日K。secid 形如 '1.600519'，beg/end 形如 '20200101'。"""
        await self._throttle()
        params = {
            "secid": secid,
            "klt": "101",      # 日K
            "fqt": "1",        # 前复权
            "beg": beg,
            "end": end,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        }
        resp = await self._client.get(_KLINE_URL, params=params)
        resp.raise_for_status()
        klines = (resp.json().get("data") or {}).get("klines") or []
        bars = []
        for line in klines:
            parts = line.split(",")
            # f51..f61: 日期,开,收,高,低,量,额,振幅,涨跌幅,涨跌额,换手率
            open_, close, high, low = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            vol = int(float(parts[5]))
            amount = float(parts[6])
            pct = float(parts[8]) if parts[8] else 0.0
            turnover = float(parts[10]) if parts[10] else 0.0
            vwap = round(amount / (vol * 100), 3) if vol > 0 else 0.0
            bars.append(KlineBar(
                date=parts[0], open=open_, close=close, high=high, low=low,
                volume=vol, amount=amount, pct_change=pct,
                turnover_rate=turnover, vwap=vwap,
            ))
        return bars
```

- [ ] **Step 2: 追加测试**

```python
@pytest.mark.asyncio
async def test_fetch_daily_kline_parses_and_computes_vwap(respx_mock):
    # 一行: 日期,开,收,高,低,量(手),额,振幅,涨跌幅,涨跌额,换手率
    sample = "2026-06-13,1680.00,1685.00,1690.00,1675.00,10000,1683000000,0.89,0.30,5.0,0.8"
    respx_mock.get("https://push2his.eastmoney.com/api/qt/stock/kline/get").mock(
        return_value=httpx.Response(200, json={"data": {"klines": [sample]}})
    )
    async with EastMoneyClient() as em:
        bars = await em.fetch_daily_kline("1.600519", "20260101", "20261231")
    assert len(bars) == 1
    b = bars[0]
    assert b.date == "2026-06-13"
    assert b.close == 1685.00
    assert b.volume == 10000
    assert b.turnover_rate == 0.8
    assert b.pct_change == 0.30
    # vwap = amount / (vol*100) = 1683000000 / (10000*100) = 1683.0
    assert b.vwap == 1683.0


@pytest.mark.asyncio
async def test_fetch_daily_kline_zero_volume_no_div_zero(respx_mock):
    sample = "2026-06-13,0,0,0,0,0,0,0,0,0,0"  # 停牌
    respx_mock.get("https://push2his.eastmoney.com/api/qt/stock/kline/get").mock(
        return_value=httpx.Response(200, json={"data": {"klines": [sample]}})
    )
    async with EastMoneyClient() as em:
        bars = await em.fetch_daily_kline("1.600519", "20260101", "20261231")
    assert bars[0].vwap == 0.0


@pytest.mark.asyncio
async def test_fetch_daily_kline_handles_missing_data(respx_mock):
    respx_mock.get("https://push2his.eastmoney.com/api/qt/stock/kline/get").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    async with EastMoneyClient() as em:
        bars = await em.fetch_daily_kline("1.600519", "20260101", "20261231")
    assert bars == []
```

- [ ] **Step 3: 运行测试**

Run:
```bash
cd /d/Codes/ChipScope/backend
.venv/Scripts/python -m pytest tests/test_eastmoney.py -v
```
Expected: 5 passed（含 Task 7 的 2 个）。

- [ ] **Step 4: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/app/services/collector/eastmoney.py backend/tests/test_eastmoney.py
git commit -m "feat(collector): eastmoney daily kline (qfq) client with vwap calc"
```

---

## Task 10: 日K采集服务（交易日归一化 + upsert）+ 测试

**Files:**
- Create: `backend/app/utils/time.py`
- Modify: `backend/app/services/ingest.py`（追加 upsert_daily_kline、ingest_daily_kline 编排）
- Modify: `backend/tests/test_ingest.py`

- [ ] **Step 1: 写 utils/time.py（把 "2026-06-13" 归一化为北京时间 15:30 的 aware datetime）**

```python
from datetime import datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo

_CST = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc


def trading_day_ts(date_str: str) -> datetime:
    """交易日字符串 '2026-06-13' → 该日 15:30 北京时间的 UTC-aware datetime。"""
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    local = datetime.combine(d, time(15, 30), tzinfo=_CST)
    return local.astimezone(UTC)
```

- [ ] **Step 2: 在 ingest.py 追加日K upsert + 编排**

```python
from app.utils.time import trading_day_ts


async def upsert_daily_kline(session: AsyncSession, secucode: str, bars: list[KlineBar]) -> int:
    if not bars:
        return 0
    rows = [{
        "ts": trading_day_ts(b.date),
        "secucode": secucode,
        "open": b.open, "close": b.close, "high": b.high, "low": b.low,
        "volume": b.volume, "amount": b.amount,
        "turnover_rate": b.turnover_rate, "pct_change": b.pct_change, "vwap": b.vwap,
    } for b in bars]
    stmt = insert(DailyKline).values(rows)
    first = rows[0]
    update_cols = {c: stmt.excluded[c] for c in first if c not in ("secucode", "ts")}
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyKline.secucode, DailyKline.ts], set_=update_cols
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def ingest_daily_kline(em, session: AsyncSession, secucode: str, secid: str,
                             beg: str, end: str) -> int:
    """编排：拉取 + 落库。em 为 EastMoneyClient 实例。"""
    bars = await em.fetch_daily_kline(secid, beg, end)
    return await upsert_daily_kline(session, secucode, bars)
```

- [ ] **Step 3: 追加测试（验证归一化时区 + upsert 幂等）**

```python
from app.models.kline import DailyKline
from app.services.ingest import upsert_daily_kline
from app.services.collector.types import KlineBar
from app.utils.time import trading_day_ts


@pytest.mark.asyncio
async def test_upsert_daily_kline_normalizes_tz_and_is_idempotent(session):
    bars = [KlineBar("2026-06-13", 1680, 1685, 1690, 1675, 10000, 1.683e9, 0.3, 0.8, 1683.0)]
    n1 = await upsert_daily_kline(session, "600519.SH", bars)
    assert n1 == 1
    from sqlalchemy import select
    rows = (await session.execute(select(DailyKline))).scalars().all()
    assert len(rows) == 1
    assert rows[0].ts == trading_day_ts("2026-06-13")  # 北京15:30→UTC
    assert rows[0].turnover_rate == 0.8

    # 重复 upsert 不新增
    n2 = await upsert_daily_kline(session, "600519.SH", bars)
    assert n2 == 1
    rows = (await session.execute(select(DailyKline))).scalars().all()
    assert len(rows) == 1
```

- [ ] **Step 4: 运行测试**

Run:
```bash
cd /d/Codes/ChipScope/backend
.venv/Scripts/python -m pytest tests/test_ingest.py -v
```
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/app/utils backend/app/services/ingest.py backend/tests/test_ingest.py
git commit -m "feat(ingest): daily kline ingest with tz normalization and idempotent upsert"
```

---

## Task 11: REST API — 股票列表 + 测试

**Files:**
- Create: `backend/app/schemas/stock.py`
- Create: `backend/app/api/deps.py`
- Create: `backend/app/api/stocks.py`
- Create: `backend/tests/test_api_stocks.py`

- [ ] **Step 1: 写 schemas/stock.py**

```python
from pydantic import BaseModel


class StockOut(BaseModel):
    secucode: str
    code: str
    name: str
    market: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: 写 api/deps.py**

```python
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import SessionLocal


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
```

- [ ] **Step 3: 写 api/stocks.py（列表 + 搜索）**

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.models.stock import StockMeta
from app.schemas.stock import StockOut

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("", response_model=list[StockOut])
async def list_stocks(
    q: str | None = Query(None, description="按代码或名称模糊搜索"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(StockMeta)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(StockMeta.code.like(like), StockMeta.name.like(like)))
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows
```

- [ ] **Step 4: 写测试（httpx ASGITransport，内存 DB）**

```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models.base import Base
from app.models.stock import StockMeta
import app.api.deps as deps


@pytest.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with Session() as s:
            yield s

    # 预置数据
    async with Session() as s:
        s.add_all([
            StockMeta(secucode="600519.SH", code="600519", name="贵州茅台", market="SH", secid="1.600519"),
            StockMeta(secucode="000001.SZ", code="000001", name="平安银行", market="SZ", secid="0.000001"),
        ])
        await s.commit()

    from app.main import app
    monkeypatch.setattr(deps, "SessionLocal", Session)
    app.dependency_overrides[deps.get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_stocks_no_filter(client):
    r = await client.get("/api/stocks")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2


@pytest.mark.asyncio
async def test_list_stocks_search_by_code(client):
    r = await client.get("/api/stocks", params={"q": "600519"})
    data = r.json()
    assert len(data) == 1 and data[0]["secucode"] == "600519.SH"


@pytest.mark.asyncio
async def test_list_stocks_search_by_name(client):
    r = await client.get("/api/stocks", params={"q": "平安"})
    data = r.json()
    assert len(data) == 1 and data[0]["name"] == "平安银行"
```

> **注意：** `from app.main import app` 需要 Task 13 的 main.py 存在。本 task 先写 API 与测试，main.py 在 Task 13 装配后此测试才能跑通——执行时可调整顺序：先做 Task 13 的最小 main.py，再回头跑此测试。或者把 Task 11/12/13 视为一组连续执行。

- [ ] **Step 5: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/app/schemas backend/app/api backend/tests/test_api_stocks.py
git commit -m "feat(api): stock list with search endpoint"
```

---

## Task 12: REST API — K线查询 + 测试

**Files:**
- Create: `backend/app/schemas/kline.py`
- Modify: `backend/app/api/stocks.py`（追加 kline 路由）
- Modify: `backend/tests/test_api_stocks.py`（追加测试）

- [ ] **Step 1: 写 schemas/kline.py**

```python
from datetime import datetime
from pydantic import BaseModel


class KlineOut(BaseModel):
    ts: datetime
    open: float
    close: float
    high: float
    low: float
    volume: int
    amount: float
    turnover_rate: float
    pct_change: float
    vwap: float

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: 在 api/stocks.py 追加 kline 路由**

```python
from datetime import datetime
from app.models.kline import DailyKline
from app.schemas.kline import KlineOut


@router.get("/{secucode}/kline", response_model=list[KlineOut])
async def get_kline(
    secucode: str,
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    limit: int = Query(500, le=5000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(DailyKline).where(DailyKline.secucode == secucode)
    if start:
        stmt = stmt.where(DailyKline.ts >= start)
    if end:
        stmt = stmt.where(DailyKline.ts <= end)
    stmt = stmt.order_by(DailyKline.ts).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows
```

- [ ] **Step 3: 追加测试（client fixture 复用 Task 11，预置一条 K 线）**

在 `test_api_stocks.py` 的 client fixture 预置数据处加：
```python
from app.models.kline import DailyKline
from app.utils.time import trading_day_ts
# ...在 add_all 后追加：
        s.add(DailyKline(
            ts=trading_day_ts("2026-06-13"), secucode="600519.SH",
            open=1680, close=1685, high=1690, low=1675,
            volume=10000, amount=1.683e9, turnover_rate=0.8,
            pct_change=0.3, vwap=1683.0,
        ))
```

新增测试：
```python
@pytest.mark.asyncio
async def test_get_kline_returns_bars(client):
    r = await client.get("/api/stocks/600519.SH/kline")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["close"] == 1685.0
    assert data[0]["vwap"] == 1683.0


@pytest.mark.asyncio
async def test_get_kline_empty_for_unknown(client):
    r = await client.get("/api/stocks/999999.SH/kline")
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 4: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/app/schemas/kline.py backend/app/api/stocks.py backend/tests/test_api_stocks.py
git commit -m "feat(api): daily kline query endpoint"
```

---

## Task 13: FastAPI 应用装配 + 冒烟

**Files:**
- Create: `backend/app/main.py`

- [ ] **Step 1: 写 main.py**

```python
from fastapi import FastAPI
from app.api.stocks import router as stocks_router

app = FastAPI(title="ChipScope API", version="0.1.0")

app.include_router(stocks_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 2: 跑全部测试（此时 Task 11/12 的 API 测试应通过）**

Run:
```bash
cd /d/Codes/ChipScope/backend
.venv/Scripts/python -m pytest -v
```
Expected: 全部 passed（约 9 个测试）。

- [ ] **Step 3: 本地启动冒烟（连真实 docker PG）**

Run:
```bash
cd /d/Codes/ChipScope/backend
.venv/Scripts/uvicorn app.main:app --reload
```
另开终端：
```bash
curl http://localhost:8000/health
curl http://localhost:8000/docs   # 查看自动文档
```
Expected: `/health` 返回 `{"status":"ok"}`。

- [ ] **Step 4: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/app/main.py
git commit -m "feat: FastAPI app assembly with health check"
```

---

## Task 14: 端到端手动验证（采集真实数据）

> 此 task 不写测试代码，是手动验证脚本，确认整条链路在真实网络下通。

**Files:**
- Create: `backend/scripts/smoke_ingest.py`

- [ ] **Step 1: 写 scripts/smoke_ingest.py**

```python
"""手动冒烟：拉茅台全市场列表 + 茅台近 30 日K，写入本地 docker PG。"""
import asyncio
from app.database import SessionLocal
from app.services.collector.eastmoney import EastMoneyClient
from app.services.ingest import upsert_stock_meta, ingest_daily_kline


async def main():
    async with EastMoneyClient() as em:
        stocks = await em.list_stocks()
        print(f"list_stocks: {len(stocks)} 只")
        async with SessionLocal() as session:
            n = await upsert_stock_meta(session, stocks)
            print(f"upsert_stock_meta: {n} 行")

            # 找茅台
            moutai = next((s for s in stocks if s.code == "600519"), None)
            assert moutai, "未找到 600519"
            m = await ingest_daily_kline(em, session, moutai.secucode, moutai.secid,
                                         beg="20260501", end="20260613")
            print(f"ingest 600519 日K: {m} 根")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 运行（需 docker PG 已起、网络可访问东财）**

Run:
```bash
cd /d/Codes/ChipScope/backend
.venv/Scripts/python scripts/smoke_ingest.py
```
Expected: 打印列表数量、upsert 行数、茅台日K根数（应为 ~25 个交易日）。

- [ ] **Step 3: 用 API 验证**

```bash
curl "http://localhost:8000/api/stocks?q=600519"
curl "http://localhost:8000/api/stocks/600519.SH/kline?limit=5"
```
Expected: 返回茅台元数据与近 5 根日K（含换手率、vwap）。

- [ ] **Step 4: Commit**

```bash
cd /d/Codes/ChipScope
git add backend/scripts/smoke_ingest.py
git commit -m "chore: end-to-end smoke script for eastmoney ingest"
```

---

## Self-Review

**1. Spec coverage（对照设计文档）：**
- 日K线采集（东财前复权）→ Task 7/9/10/14 ✓
- 换手率 → Task 9（东财 f61）✓，P0-1 已消解
- 复权 → Task 9（fqt=1）✓，P0-2 已解决
- 数据库设计 daily_kline / stock_meta → Task 5/6 ✓
- REST API /api/stocks、/api/stocks/{code}/kline → Task 11/12 ✓
- **本 plan 不覆盖**（留给后续 plan）：mootdx 实时行情/分笔、股东/资金流、筹码引擎、形态识别、WebSocket、前端、调度器自动运行（仅提供手动触发函数）。这是按 Scope Check 拆分的预期结果。

**2. Placeholder scan：** 无 TBD/TODO；每个代码步骤含完整可运行代码。

**3. 类型一致性：** `StockInfo`/`KlineBar` 在 Task 7 定义，在 Task 8/9/10 一致使用；`secucode` 格式 `600519.SH`、`secid` 格式 `1.600519` 全程一致；`DailyKline.ts` 用 `trading_day_ts` 归一化为 UTC aware，API 与模型字段一致。

**已知边界/风险：**
- 测试用 SQLite 内存库（需 aiosqlite），生产用 PostgreSQL——upsert 语义 `on_conflict_do_update` 在 SQLite 也支持，但生产 PG 的 TimescaleDB 行为需 Task 14 真实验证。
- 东财接口字段以实际抓包为准；Task 14 冒烟即首次真实校验。若字段顺序变化，Task 9 解析需调整。
- 北交所（BJ）暂不支持（fs 未含 `m:0 t:81`），后续 plan 补。
