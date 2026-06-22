import asyncio
import json

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import get_settings
from app.database import SessionLocal
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.schemas.watchlist import ReorderRequest, WatchlistCreateRequest, WatchlistItemOut
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.tdx_client import TdxClient
from app.services.collector.types import StockInfo
from app.services.ingest import upsert_stock_meta
from app.services.kline_chip import ingest_kline_and_chips

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

SCOPE = "default"


async def _read_quote(secucode: str) -> dict | None:
    r = aioredis.from_url(get_settings().redis_url)
    try:
        raw = await r.get(f"quote:{secucode}")
        return json.loads(raw) if raw else None
    finally:
        await r.aclose()


@router.get("", response_model=list[WatchlistItemOut])
async def list_watchlist(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Watchlist, StockMeta)
        .join(StockMeta, Watchlist.secucode == StockMeta.secucode)
        .where(Watchlist.scope == SCOPE)
        .order_by(Watchlist.sort_order)
    )
    rows = (await db.execute(stmt)).all()
    out: list[WatchlistItemOut] = []
    for w, s in rows:
        q = await _read_quote(w.secucode)
        out.append(WatchlistItemOut(
            secucode=w.secucode,
            code=s.code,
            name=s.name,
            industry=s.industry,
            sort_order=w.sort_order,
            created_at=w.created_at,
            price=q.get("price") if q else None,
            pct_change=q.get("pct_change") if q else None,
        ))
    return out


async def _ensure_stock_meta(db: AsyncSession, secucode: str) -> StockMeta | None:
    """stock_meta 无该 secucode 时调东财查证并补元数据。

    - 东财命中：upsert 真实元数据
    - 东财明确查无（返回空列表）：返回 None（调用方应 400）
    - 东财故障（网络/限流）：用 secucode 解析兜底（name 缺失，后续 ingest 补）

    返回补入后的 StockMeta；北交所等非沪深市场返回 None。
    """
    code, _, market = secucode.partition(".")
    if market not in ("SH", "SZ"):
        return None
    try:
        async with EastMoneyClient() as em:
            results = await em.search_stocks(code, count=1)
    except Exception:
        results = None  # 网络/限流 → 走兜底
    if results:
        await upsert_stock_meta(db, results[:1])
    elif results is None:
        secid = ("1" if market == "SH" else "0") + "." + code
        await upsert_stock_meta(db, [StockInfo(secucode, code, code, market, secid)])
    else:  # results == [] 东财明确查无
        return None
    return (
        await db.execute(select(StockMeta).where(StockMeta.secucode == secucode))
    ).scalar_one_or_none()


# 后台采集 task 引用集合：持有以防 GC，task 完成后自动移除。
_background_tasks: set[asyncio.Task] = set()


async def _ingest_in_background(secucode: str, secid: str) -> None:
    """后台采集历史日K + 筹码：自建 db session / TdxClient / EastMoneyClient。

    请求级 session 在响应返回后即关闭，故此处用 SessionLocal 自建；mootdx 同步调用
    已在 TdxClient.daily_bars 内部 run_in_executor。异常仅记日志——watchlist 行已
    commit，采集失败不得影响已返回的 201。
    """
    tdx = TdxClient()
    try:
        async with SessionLocal() as session:
            async with EastMoneyClient() as em:
                r = await ingest_kline_and_chips(
                    tdx, em, session, secucode, secid,
                    days=get_settings().kline_history_days,
                )
        print(f"[watchlist] {secucode} ingested: {r}")
    except Exception as e:
        print(f"[watchlist] {secucode} kline/chip ingest failed: {e}")
    finally:
        tdx.close()


def _schedule_ingest(secucode: str, secid: str) -> None:
    """后台 fire-and-forget 触发采集；持有 task 引用防 GC，完成后自动移除。"""
    task = asyncio.create_task(_ingest_in_background(secucode, secid))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.post("", response_model=WatchlistItemOut, status_code=201)
async def add_watchlist(
    body: WatchlistCreateRequest, db: AsyncSession = Depends(get_db)
):
    exists = (
        await db.execute(select(StockMeta).where(StockMeta.secucode == body.secucode))
    ).scalar_one_or_none()
    if not exists:
        exists = await _ensure_stock_meta(db, body.secucode)
        if exists is None:
            raise HTTPException(status_code=400, detail="stock not found")

    max_order = (
        await db.execute(
            select(func.coalesce(func.max(Watchlist.sort_order), -1)).where(
                Watchlist.scope == SCOPE
            )
        )
    ).scalar_one()
    stmt = (
        insert(Watchlist)
        .values(secucode=body.secucode, scope=SCOPE, sort_order=max_order + 1)
        .on_conflict_do_nothing(index_elements=[Watchlist.scope, Watchlist.secucode])
    )
    await db.execute(stmt)
    await db.commit()

    # 后台异步采集历史日K + 筹码（K线走 mootdx TCP，绕过东财反爬）。
    # 采集在后台跑，POST 立即返回；watchlist 行已 commit，采集失败仅记日志、不回滚。
    _schedule_ingest(body.secucode, exists.secid)

    row = (
        await db.execute(
            select(Watchlist).where(
                Watchlist.scope == SCOPE, Watchlist.secucode == body.secucode
            )
        )
    ).scalar_one()
    return WatchlistItemOut(
        secucode=row.secucode,
        code=exists.code,
        name=exists.name,
        industry=exists.industry,
        sort_order=row.sort_order,
        created_at=row.created_at,
    )


@router.delete("/{secucode}", status_code=204)
async def delete_watchlist(secucode: str, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(Watchlist).where(
                Watchlist.scope == SCOPE, Watchlist.secucode == secucode
            )
        )
    ).scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return Response(status_code=204)


@router.put("/reorder", status_code=204)
async def reorder_watchlist(
    body: ReorderRequest, db: AsyncSession = Depends(get_db)
):
    for idx, secucode in enumerate(body.secucodes):
        row = (
            await db.execute(
                select(Watchlist).where(
                    Watchlist.scope == SCOPE, Watchlist.secucode == secucode
                )
            )
        ).scalar_one_or_none()
        if row:
            row.sort_order = idx
    await db.commit()
    return Response(status_code=204)
