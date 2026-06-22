import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.base import Base
from app.models.stock import StockMeta
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.types import StockInfo


@pytest_asyncio.fixture
async def watchlist_client():
    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        # 同 conftest db_session：每用例重建最新 schema，避免旧测试库缺唯一约束/缺列
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
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
    import app.api.watchlist as wl
    app.dependency_overrides[get_db] = override_get_db
    # add_watchlist 现后台触发采集；这些测试只验证 watchlist 增删改查，桩掉 _schedule_ingest
    # 以免后台 task 真实连 mootdx 并在 teardown 后 race。respx 仅作未 mock 请求的安全网。
    _orig_schedule = wl._schedule_ingest
    wl._schedule_ingest = lambda secucode, secid: None
    transport = ASGITransport(app=app)
    with respx.mock(assert_all_called=False) as rx:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    wl._schedule_ingest = _orig_schedule
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
async def test_add_unknown_secucode_400(watchlist_client, monkeypatch):
    """stock_meta 无时先调东财查证，东财也查无才 400。"""
    calls = []

    async def fake_search(self, q, count=10):
        calls.append(q)
        return []

    monkeypatch.setattr(EastMoneyClient, "search_stocks", fake_search)
    r = await watchlist_client.post("/api/watchlist", json={"secucode": "999999.SZ"})
    assert r.status_code == 400
    assert calls == ["999999"]


@pytest.mark.asyncio
async def test_add_auto_fills_meta_from_eastmoney(watchlist_client, monkeypatch):
    """stock_meta 无 + 东财命中 → 自动补元数据 + 201。"""
    async def fake_search(self, q, count=10):
        assert q == "600036"
        return [StockInfo("600036.SH", "600036", "招商银行", "SH", "1.600036")]
    monkeypatch.setattr(EastMoneyClient, "search_stocks", fake_search)

    r = await watchlist_client.post("/api/watchlist", json={"secucode": "600036.SH"})
    assert r.status_code == 201

    data = (await watchlist_client.get("/api/watchlist")).json()
    assert any(d["secucode"] == "600036.SH" and d["name"] == "招商银行" for d in data)


@pytest.mark.asyncio
async def test_add_falls_back_on_eastmoney_error(watchlist_client, monkeypatch):
    """东财网络失败 → 用 secucode 解析兜底补最小元数据 + 201（name 缺失）。"""
    async def fake_search(self, q, count=10):
        raise RuntimeError("network down")
    monkeypatch.setattr(EastMoneyClient, "search_stocks", fake_search)

    r = await watchlist_client.post("/api/watchlist", json={"secucode": "600036.SH"})
    assert r.status_code == 201


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
