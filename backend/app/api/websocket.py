from fastapi import APIRouter, WebSocket

from app.services.realtime import manager

router = APIRouter()


@router.websocket("/ws/realtime/{code}")
async def realtime(ws: WebSocket, code: str):
    """客户端连接后保持，接收该 code 的实时行情广播。"""
    await manager.connect(code, ws)
    try:
        while True:
            await ws.receive_text()  # 保活：等待客户端消息（或断开）
    except Exception:
        manager.disconnect(code, ws)
