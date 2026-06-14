import json

import redis.asyncio as aioredis
from fastapi import WebSocket

from app.config import get_settings


class ConnectionManager:
    """WebSocket 连接管理器，按股票代码分组做 fan-out 广播。"""

    def __init__(self) -> None:
        self._subs: dict[str, set[WebSocket]] = {}

    async def connect(self, code: str, ws: WebSocket) -> None:
        await ws.accept()
        self._subs.setdefault(code, set()).add(ws)

    def disconnect(self, code: str, ws: WebSocket) -> None:
        self._subs.get(code, set()).discard(ws)

    async def broadcast(self, code: str, data: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._subs.get(code, set())):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(code, ws)


manager = ConnectionManager()


async def cache_quote(quote) -> None:
    """实时行情写 Redis（10s 过期）。"""
    r = aioredis.from_url(get_settings().redis_url)
    try:
        payload = {
            "secucode": quote.secucode,
            "price": quote.price,
            "open": quote.open,
            "high": quote.high,
            "low": quote.low,
            "bids": quote.bids,
            "asks": quote.asks,
        }
        await r.set(f"quote:{quote.secucode}", json.dumps(payload), ex=10)
    finally:
        await r.aclose()
