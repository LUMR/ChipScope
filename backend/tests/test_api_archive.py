"""archive 路由测试：日K存档 + 指标物化 API。

对齐 test_api_market 的 ASGITransport + AsyncClient 模式；monkeypatch
`kline_archive.archive_daily_klines` / `metric_archive.archive_metrics_range`
避免真实 TdxClient / DB 写入。

注意：metric 用例必须打 import 站点 `app.api.archive.archive_metrics_range`，
因为 archive.py 是 `from app.services.metric_archive import archive_metrics_range`
按值绑定本地名 —— 打 metric_archive 模块属性不会触及 archive.py 已绑的本地名，
fake 不会生效。
"""
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import kline_archive, metric_archive


@pytest.mark.asyncio
async def test_daily_kline_archive_trigger_and_status(monkeypatch):
    calls: list[tuple] = []

    async def _fake(session_factory, tdx, trade_date, count=250, on_progress=None):
        calls.append((trade_date, count))
        return {"trade_date": trade_date.strftime("%Y-%m-%d"), "total": 1, "ok": 1, "failed": 0}

    # 打 import 站点：archive.py 是 `from ... import archive_daily_klines`
    # 按值绑定本地名，必须改 archive 模块的属性才能让 _run_daily_kline_archive 调到 fake。
    monkeypatch.setattr("app.api.archive.archive_daily_klines", _fake)
    kline_archive.reset_daily_kline_archive_state()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/archive/daily?count=10")
        assert r.status_code == 202
        assert "trade_date" in r.json()
        # 后台任务由 ASGI app 同一 loop 的 asyncio.create_task 调度，
        # 短轮询有界等待它跑完并落到内存状态。
        status = None
        for _ in range(40):  # ≤2s 硬上限，防 hang
            await asyncio.sleep(0.05)
            s = await ac.get("/api/archive/daily/status")
            assert s.status_code == 200
            status = s.json()
            if status and status.get("state") == "done":
                break
        # 证明 fake 真的被调到（不是空 DB 下真函数的偶然成功）
        assert calls, "fake archive_daily_klines was never called — patch ineffective"
        # 证明 fake 的返回值已贯穿进 status
        assert status is not None
        assert status["state"] == "done"
        assert status["ok"] == 1
        assert status["total"] == 1


@pytest.mark.asyncio
async def test_metrics_archive_trigger_and_status(monkeypatch):
    calls: list[tuple] = []

    async def _fake_range(session_factory, start, end, on_progress=None):
        calls.append((start, end))
        return {"start": str(start), "end": str(end), "days": 1, "ok": 1, "failed": 0}

    # 打 import 站点：archive.py 是 `from ... import archive_metrics_range`
    # 按值绑定本地名，必须改 archive 模块的属性才能让 _run_metrics_archive 调到 fake。
    monkeypatch.setattr("app.api.archive.archive_metrics_range", _fake_range)
    metric_archive.reset_metrics_archive_state()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/archive/metrics?days=60")
        assert r.status_code == 202
        # 后台任务由 ASGI app 同一 loop 的 asyncio.create_task 调度，
        # 短轮询有界等待它跑完并落到内存状态。
        status = None
        for _ in range(40):  # ≤2s 硬上限，防 hang
            await asyncio.sleep(0.05)
            s = await ac.get("/api/archive/metrics/status")
            assert s.status_code == 200
            status = s.json()
            if status and status.get("state") == "done":
                break
        # 证明 fake 真的被调到（不是空 DB 下真函数的偶然成功）
        assert calls, "fake archive_metrics_range was never called — patch ineffective"
        # 证明 fake 的返回值已贯穿进 status
        assert status is not None
        assert status["state"] == "done"
        assert status["ok"] == 1
        assert status["total"] == 1
