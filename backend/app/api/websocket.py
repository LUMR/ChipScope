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


@router.websocket("/ws/realtime")
async def realtime_all(ws: WebSocket):
    """全局订阅：单连接接收所有自选股实时行情。消息含 secucode 字段。"""
    await manager.connect_global(ws)
    try:
        while True:
            await ws.receive_text()
    except Exception:
        manager.disconnect_global(ws)
