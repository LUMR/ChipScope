import json

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import get_settings
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.schemas.watchlist import ReorderRequest, WatchlistCreateRequest, WatchlistItemOut

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
            pct_change=None,  # quote 缓存暂无 pct_change，留空
        ))
    return out


@router.post("", response_model=WatchlistItemOut, status_code=201)
async def add_watchlist(
    body: WatchlistCreateRequest, db: AsyncSession = Depends(get_db)
):
    exists = (
        await db.execute(select(StockMeta).where(StockMeta.secucode == body.secucode))
    ).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=400, detail="secucode not in stock_meta")

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
