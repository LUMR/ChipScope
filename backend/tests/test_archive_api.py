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
async def test_status_empty(monkeypatch):
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
async def test_trigger_then_status_done(monkeypatch):
    import app.api.archive as arch

    async def _fake_run(td):
        set_archive_status({"state": "done", "trade_date": str(td),
                            "total": 2, "done": 2, "ok": 2, "failed": 0})
    monkeypatch.setattr(arch, "_run_archive", _fake_run)

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as ac:
        r = await ac.post("/api/archive/minute")
        assert r.status_code == 202
        import asyncio
        await asyncio.sleep(0.1)
        s = await ac.get("/api/archive/minute/status")
        assert s.status_code == 200
        body = s.json()
        assert body["state"] == "done"
        assert body["ok"] == 2
        assert body["done"] == 2


@pytest.mark.asyncio
async def test_trigger_rejects_when_running(monkeypatch):
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


@pytest.mark.asyncio
async def test_trigger_bad_date_returns_422(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/archive/minute", params={"date": "not-a-date"})
        assert r.status_code == 422
