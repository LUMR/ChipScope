"""archive 路由测试：日K存档 API。

对齐 test_api_market 的 ASGITransport + AsyncClient 模式；monkeypatch
`kline_archive.archive_daily_klines` 避免真实 TdxClient / DB 写入。
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import kline_archive


@pytest.mark.asyncio
async def test_daily_kline_archive_trigger_and_status(monkeypatch):
    async def _fake(session_factory, tdx, trade_date, count=250, on_progress=None):
        return {"trade_date": trade_date.strftime("%Y-%m-%d"), "total": 1, "ok": 1, "failed": 0}

    monkeypatch.setattr(kline_archive, "archive_daily_klines", _fake)
    kline_archive.reset_daily_kline_archive_state()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/archive/daily?count=10")
        assert r.status_code == 202
        assert "trade_date" in r.json()
        s = await ac.get("/api/archive/daily/status")
        assert s.status_code == 200
