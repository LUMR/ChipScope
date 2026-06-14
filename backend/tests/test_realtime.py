import pytest

from app.services.realtime import ConnectionManager


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
