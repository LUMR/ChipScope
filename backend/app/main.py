from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.chips import router as chips_router
from app.api.stocks import router as stocks_router
from app.api.archive import router as archive_router
from app.api.watchlist import router as watchlist_router
from app.api.websocket import router as ws_router
from app.config import get_settings
from app.scheduler import build_scheduler, seed_watchlist_if_empty

# backend/app/main.py → 上三级即项目根
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_frontend_dist() -> Path | None:
    """定位前端构建产物目录；index.html 不存在则返回 None（退化为纯 API 服务）。"""
    settings = get_settings()
    dist = (
        Path(settings.frontend_dist)
        if settings.frontend_dist
        else _PROJECT_ROOT / "frontend" / "dist"
    )
    return dist if (dist / "index.html").exists() else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """单进程单端口：FastAPI 内嵌定时任务（受 CHIPSCOPE_SCHEDULER_ENABLED 控制）。"""
    if get_settings().scheduler_enabled:
        await seed_watchlist_if_empty()
        sched = build_scheduler()
        sched.start()
        app.state.scheduler = sched
        print(
            "scheduler embedded: realtime every 3s, "
            "holders/flow at 16:00 (Asia/Shanghai)"
        )
    else:
        print("scheduler disabled (CHIPSCOPE_SCHEDULER_ENABLED=false)")
    try:
        yield
    finally:
        sched = getattr(app.state, "scheduler", None)
        if sched is not None:
            sched.shutdown(wait=False)


app = FastAPI(title="ChipScope API", version="0.1.0", lifespan=lifespan)

app.include_router(stocks_router)
app.include_router(chips_router)
app.include_router(ws_router)
app.include_router(watchlist_router)
app.include_router(archive_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# 前端静态托管（SPA）。dist 不存在时跳过，保持纯 API 服务能力。
_DIST = _resolve_frontend_dist()
if _DIST is not None:
    _ASSETS = _DIST / "assets"
    if _ASSETS.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_ASSETS)), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # /api、/ws、/health 已被上方路由优先匹配；命中此处的多为 SPA 前端路由。
        # 对未注册的 /api/*、/ws/* 显式 404，避免被当成前端页面返回 index.html。
        if full_path.startswith(("api/", "ws/")) or full_path in ("api", "ws"):
            raise HTTPException(status_code=404)
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_DIST / "index.html"))
