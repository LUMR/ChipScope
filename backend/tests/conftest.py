import os

# 测试强制连独立测试库 chipscope_test，避免每个用例的 TRUNCATE 误伤开发库 chipscope。
# 必须在任何 app 模块 import 之前 setdefault——database.py 模块级 engine 会在 import 时
# 调 get_settings()，此处设的环境变量（pydantic-settings 中优先级高于 .env）使其连测试库。
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
import app.models.stock_metric  # noqa: F401

_TRUNCATE_TABLES = (
    "stock_meta, daily_kline, top_holders, holder_summary, money_flow, "
    "chip_distribution, watchlist, minute_quote, stock_metric"
)


@pytest.fixture
def respx_mock():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest_asyncio.fixture
async def db_session():
    """每个测试独立的 engine + session。

    pytest-asyncio 默认每个测试一个 event loop，模块级 engine 会跨 loop
    复用连接（Windows ProactorEventLoop 下报 proactor.send None），
    因此 engine 在 fixture 内创建并 dispose。测试前后 TRUNCATE 隔离数据。
    """
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with engine.begin() as conn:
        # 每用例彻底重建 schema：drop_all + create_all 保证表结构与最新 model 一致。
        # create_all 不修改已存在的表——旧测试库会漂移（缺列/缺唯一约束，如 watchlist 的
        # (scope,secucode) 约束、minute_quote 的 pre_close）。drop 后重建即永远最新。
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(f"TRUNCATE {_TRUNCATE_TABLES} CASCADE"))
    async with SessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_TRUNCATE_TABLES} CASCADE"))
    await engine.dispose()
