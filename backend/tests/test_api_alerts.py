"""盯盘告警 API 集成测试（仿 test_api_screener：独立 engine + dependency_overrides）。"""
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.base import Base
from app.models.stock import StockMeta

_RT_RULE = {
    "name": "涨幅超5%",
    "secucodes": ["600519.SH"],
    "conditions": [
        {"scope": "realtime", "metric": "pct_change", "op": "gte", "value": 5.0},
        {"scope": "realtime", "metric": "amount", "op": "gt", "value": 1e9},
    ],
    "enabled": True,
    "cooldown_minutes": 10,
    "webhook_url": None,
}


@pytest_asyncio.fixture
async def alerts_client(respx_mock):
    from app.api.deps import get_db
    from app.main import app

    engine = create_async_engine(get_settings().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, alert_rule, alert_event CASCADE"))
    async with SessionLocal() as s:
        s.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                        market="SH", secid="1.600519"))
        await s.commit()

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE stock_meta, alert_rule, alert_event CASCADE"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_metrics(alerts_client):
    r = await alerts_client.get("/api/alerts/metrics")
    assert r.status_code == 200
    data = r.json()
    scopes = {m["scope"] for m in data}
    assert scopes == {"realtime", "chip", "pattern"}
    pat = next(m for m in data if m["metric"] == "pattern")
    assert pat["ops"] == ["eq", "ne"]
    assert {"value": "single_peak_dense", "label": "单峰密集"} in pat["options"]
    price = next(m for m in data if m["metric"] == "price")
    assert "cross_above" in price["ops"]
    assert price["options"] == []


@pytest.mark.asyncio
async def test_rule_crud_full_cycle(alerts_client):
    # create
    r = await alerts_client.post("/api/alerts/rules", json=_RT_RULE)
    assert r.status_code == 201, r.text
    rule = r.json()
    assert rule["id"] > 0
    assert rule["enabled"] is True
    assert len(rule["conditions"]) == 2
    # list
    r = await alerts_client.get("/api/alerts/rules")
    assert [x["id"] for x in r.json()] == [rule["id"]]
    # update：改名 + 停用 + cooldown
    body = {**_RT_RULE, "name": "改名", "enabled": False, "cooldown_minutes": 30}
    r = await alerts_client.put(f"/api/alerts/rules/{rule['id']}", json=body)
    assert r.status_code == 200
    assert r.json()["name"] == "改名"
    assert r.json()["enabled"] is False
    assert r.json()["cooldown_minutes"] == 30
    # delete
    r = await alerts_client.delete(f"/api/alerts/rules/{rule['id']}")
    assert r.status_code == 204
    assert (await alerts_client.get("/api/alerts/rules")).json() == []


@pytest.mark.asyncio
async def test_create_rejects_mixed_scope(alerts_client):
    body = {
        **_RT_RULE,
        "conditions": [
            {"scope": "realtime", "metric": "price", "op": "gt", "value": 10},
            {"scope": "chip", "metric": "avg_cost", "op": "gt", "value": 9},
        ],
    }
    r = await alerts_client.post("/api/alerts/rules", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_unknown_metric(alerts_client):
    body = {**_RT_RULE, "conditions": [
        {"scope": "realtime", "metric": "nope", "op": "gt", "value": 1}
    ]}
    r = await alerts_client.post("/api/alerts/rules", json=body)
    assert r.status_code == 422
    # 未知 op / 数值条件用 eq 同样 422
    body = {**_RT_RULE, "conditions": [
        {"scope": "realtime", "metric": "price", "op": "between", "value": 1}
    ]}
    assert (await alerts_client.post("/api/alerts/rules", json=body)).status_code == 422
    body = {**_RT_RULE, "conditions": [
        {"scope": "realtime", "metric": "price", "op": "eq", "value": 1}
    ]}
    assert (await alerts_client.post("/api/alerts/rules", json=body)).status_code == 422
    # pattern 值非法枚举
    body = {**_RT_RULE, "conditions": [
        {"scope": "pattern", "metric": "pattern", "op": "eq", "value": "whatever"}
    ]}
    assert (await alerts_client.post("/api/alerts/rules", json=body)).status_code == 422
    # secucode 格式非法 / 重复
    body = {**_RT_RULE, "secucodes": ["600519"]}
    assert (await alerts_client.post("/api/alerts/rules", json=body)).status_code == 422
    body = {**_RT_RULE, "secucodes": ["600519.SH", "600519.SH"]}
    assert (await alerts_client.post("/api/alerts/rules", json=body)).status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_unknown_stock(alerts_client, respx_mock):
    """stock_meta 查无且东财明确查无（返回空）→ 400。"""
    respx_mock.get("https://searchapi.eastmoney.com/api/suggest/get").mock(
        return_value=httpx.Response(200, json={"QuotationCodeTable": {"Data": None}})
    )
    body = {**_RT_RULE, "secucodes": ["999999.SH"]}
    r = await alerts_client.post("/api/alerts/rules", json=body)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_chip_pattern_daily_rule_ok(alerts_client):
    """chip + pattern 混属日级，允许；realtime 单独允许。"""
    body = {
        **_RT_RULE,
        "conditions": [
            {"scope": "chip", "metric": "profit_ratio", "op": "cross_above", "value": 0.8},
            {"scope": "pattern", "metric": "trend", "op": "eq", "value": "cost_up"},
        ],
    }
    r = await alerts_client.post("/api/alerts/rules", json=body)
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_events_empty_and_rule_filter(alerts_client):
    r = await alerts_client.get("/api/alerts/events")
    assert r.status_code == 200
    assert r.json() == []
    r = await alerts_client.get("/api/alerts/events", params={"rule_id": 999})
    assert r.json() == []


@pytest.mark.asyncio
async def test_events_limit_validation(alerts_client):
    """limit 负数/超上限 → 422（防 SQLAlchemy LIMIT 负数引发 500）。"""
    r = await alerts_client.get("/api/alerts/events", params={"limit": -1})
    assert r.status_code == 422
    r = await alerts_client.get("/api/alerts/events", params={"limit": 501})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_rule_test_endpoint(alerts_client, respx_mock, monkeypatch):
    """规则级 webhook：mock 企微成功；errcode!=0 → 502；未配 webhook → 400。"""
    rule = (await alerts_client.post(
        "/api/alerts/rules", json={**_RT_RULE, "webhook_url": "https://example/hook"}
    )).json()

    # mock 规则配置的 webhook 地址（非硬编码常量端点）：发错地址则匹配不到路由
    route = respx_mock.post("https://example/hook").mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )
    r = await alerts_client.post(f"/api/alerts/rules/{rule['id']}/test")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert "贵州茅台" in body["message"]
    assert "涨跌幅(%)" in body["message"]
    assert str(route.calls.last.request.url) == "https://example/hook"
    assert route.call_count == 1

    # 发送失败 → 502
    respx_mock.post("https://example/hook").mock(
        return_value=httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid"})
    )
    r = await alerts_client.post(f"/api/alerts/rules/{rule['id']}/test")
    assert r.status_code == 502

    # 未配 webhook（规则与全局均空）→ 400（不依赖 .env，显式置空全局）
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "alert_webhook_url", "")
    rule2 = (await alerts_client.post("/api/alerts/rules", json=_RT_RULE)).json()
    r = await alerts_client.post(f"/api/alerts/rules/{rule2['id']}/test")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_missing_rule_404(alerts_client):
    r = await alerts_client.put("/api/alerts/rules/999", json=_RT_RULE)
    assert r.status_code == 404
    r = await alerts_client.delete("/api/alerts/rules/999")
    assert r.status_code == 404
