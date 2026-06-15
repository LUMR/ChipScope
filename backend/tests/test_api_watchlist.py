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
