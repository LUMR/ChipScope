import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.stock import StockMeta


@pytest.fixture
def sample_stocks():
    return [
        StockMeta(
            secucode="600519.SH", code="600519", name="贵州茅台",
            market="SH", secid="1.600519",
        ),
        StockMeta(
            secucode="000001.SZ", code="000001", name="平安银行",
            market="SZ", secid="0.000001",
        ),
    ]


@pytest_asyncio.fixture
async def api_client(sample_stocks):
    """独立 engine + 覆盖 get_db 依赖。

    覆盖 get_db 让请求走测试 engine，避免触碰 app.database 的模块级 engine
    （它跨测试 event loop 复用连接会报 'Event loop is closed'）。
    """
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stock_meta, daily_kline CASCADE"))
    async with SessionLocal() as s:
        s.add_all(sample_stocks)
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
        await conn.execute(text("TRUNCATE stock_meta, daily_kline CASCADE"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_stocks_no_filter(api_client):
    r = await api_client.get("/api/stocks")
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_list_stocks_search_by_code(api_client):
    r = await api_client.get("/api/stocks", params={"q": "600519"})
    data = r.json()
    assert len(data) == 1
    assert data[0]["secucode"] == "600519.SH"


@pytest.mark.asyncio
async def test_list_stocks_search_by_name(api_client):
    r = await api_client.get("/api/stocks", params={"q": "平安"})
    data = r.json()
    assert len(data) == 1
    assert data[0]["name"] == "平安银行"
