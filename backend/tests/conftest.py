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
        await conn.execute(text("TRUNCATE stock_meta, daily_kline, top_holders, holder_summary, money_flow, chip_distribution, watchlist CASCADE"))
    async with SessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stock_meta, daily_kline, top_holders, holder_summary, money_flow, chip_distribution, watchlist CASCADE"))
    await engine.dispose()
