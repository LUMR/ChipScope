import json

import pytest
import redis.asyncio as aioredis

from app.config import get_settings
from app.services.realtime import ConnectionManager, cache_quote


class _MockWS:
    def __init__(self, fail: bool = False):
        self.accepted = False
        self.sent: list[dict] = []
        self._fail = fail

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict) -> None:
        if self._fail:
            raise RuntimeError("disconnected")
        self.sent.append(data)


@pytest.mark.asyncio
async def test_connection_manager_broadcast_fanout():
    mgr = ConnectionManager()
    ws1, ws2 = _MockWS(), _MockWS()
    await mgr.connect("600519.SH", ws1)
    await mgr.connect("600519.SH", ws2)
    await mgr.broadcast("600519.SH", {"price": 1685.0})
    assert ws1.accepted and ws2.accepted
    assert ws1.sent == [{"price": 1685.0}]
    assert ws2.sent == [{"price": 1685.0}]


@pytest.mark.asyncio
async def test_connection_manager_disconnects_dead():
    mgr = ConnectionManager()
    ws_ok = _MockWS()
    ws_dead = _MockWS(fail=True)
    await mgr.connect("600519.SH", ws_ok)
    await mgr.connect("600519.SH", ws_dead)
    await mgr.broadcast("600519.SH", {"price": 1.0})
    # 死连接被清理，正常连接仍收到
    assert ws_dead not in mgr._subs["600519.SH"]
    assert ws_ok in mgr._subs["600519.SH"]
    assert ws_ok.sent == [{"price": 1.0}]


@pytest.mark.asyncio
async def test_connection_manager_isolation_by_code():
    mgr = ConnectionManager()
    ws_a = _MockWS()
    ws_b = _MockWS()
    await mgr.connect("600519.SH", ws_a)
    await mgr.connect("000001.SZ", ws_b)
    await mgr.broadcast("600519.SH", {"price": 1.0})
    assert ws_a.sent == [{"price": 1.0}]
    assert ws_b.sent == []  # 不同 code 不收


class _FakeQuote:
    def __init__(self, secucode, price, last_close):
        self.secucode = secucode
        self.price = price
        self.last_close = last_close
        self.open = price
        self.high = price
        self.low = price
        self.bids = []
        self.asks = []


@pytest.mark.asyncio
async def test_cache_quote_uses_full_secucode_key_and_pct_change():
    """cache_quote(secucode=...) 用全格式 secucode 作 key（与 _read_quote 一致）并计算 pct_change。"""
    r = aioredis.from_url(get_settings().redis_url)
    await r.delete("quote:600519.SH", "quote:600519")
    try:
        q = _FakeQuote("600519", price=1689.0, last_close=1650.0)
        await cache_quote(q, secucode="600519.SH")
        raw = await r.get("quote:600519.SH")
        assert raw is not None  # 全 secucode key 写入
        payload = json.loads(raw)
        assert payload["price"] == 1689.0
        assert payload["last_close"] == 1650.0
        assert payload["pct_change"] == pytest.approx(2.3636, rel=1e-3)
        assert await r.get("quote:600519") is None  # 裸 code key 不应存在
    finally:
        await r.delete("quote:600519.SH", "quote:600519")
        await r.aclose()


@pytest.mark.asyncio
async def test_connection_manager_broadcast_global_fanout():
    """全局订阅：单连接收所有自选股广播（/ws/realtime 走这条路径）。"""
    mgr = ConnectionManager()
    ws1, ws2 = _MockWS(), _MockWS()
    await mgr.connect_global(ws1)
    await mgr.connect_global(ws2)
    await mgr.broadcast_global({"secucode": "600519.SH", "price": 1689.0})
    assert ws1.accepted and ws2.accepted
    assert ws1.sent == [{"secucode": "600519.SH", "price": 1689.0}]
    assert ws2.sent == [{"secucode": "600519.SH", "price": 1689.0}]


@pytest.mark.asyncio
async def test_connection_manager_disconnects_global_dead():
    """全局广播时清理死连接，正常连接仍收到。"""
    mgr = ConnectionManager()
    ws_ok = _MockWS()
    ws_dead = _MockWS(fail=True)
    await mgr.connect_global(ws_ok)
    await mgr.connect_global(ws_dead)
    await mgr.broadcast_global({"secucode": "600519.SH", "price": 1.0})
    assert ws_dead not in mgr._global_subs
    assert ws_ok in mgr._global_subs
    assert ws_ok.sent == [{"secucode": "600519.SH", "price": 1.0}]
