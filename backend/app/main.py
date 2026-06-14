from fastapi import FastAPI

from app.api.stocks import router as stocks_router

app = FastAPI(title="ChipScope API", version="0.1.0")

app.include_router(stocks_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
