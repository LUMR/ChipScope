from fastapi import FastAPI

from app.api.chips import router as chips_router
from app.api.stocks import router as stocks_router
from app.api.websocket import router as ws_router

app = FastAPI(title="ChipScope API", version="0.1.0")

app.include_router(stocks_router)
app.include_router(chips_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
