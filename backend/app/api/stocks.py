from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.flow import MoneyFlow
from app.models.holder import TopHolder
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.services.collector.eastmoney import EastMoneyClient
from app.schemas.flow import FlowOut
from app.schemas.holder import HolderOut
from app.schemas.kline import KlineOut
from app.schemas.stock import StockOut

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("", response_model=list[StockOut])
async def list_stocks(
    q: str | None = Query(None, description="按代码或名称模糊搜索；q 非空走东财实时联想"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    # q 非空：实时查东财 suggest（本地 stock_meta 不全，纯东财无盲区、永远最新）
    if q:
        async with EastMoneyClient() as em:
            return await em.search_stocks(q, count=limit)
    # q 为空：返回本地已采集的股票
    stmt = select(StockMeta).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/{secucode}/kline", response_model=list[KlineOut])
async def get_kline(
    secucode: str,
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    limit: int = Query(500, le=5000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(DailyKline).where(DailyKline.secucode == secucode)
    if start:
        stmt = stmt.where(DailyKline.ts >= start)
    if end:
        stmt = stmt.where(DailyKline.ts <= end)
    stmt = stmt.order_by(DailyKline.ts).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/{secucode}/holders", response_model=list[HolderOut])
async def get_holders(
    secucode: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(TopHolder)
        .where(TopHolder.secucode == secucode)
        .order_by(TopHolder.ts.desc(), TopHolder.rank)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/{secucode}/flow", response_model=list[FlowOut])
async def get_flow(
    secucode: str,
    limit: int = Query(120, le=1000),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(MoneyFlow)
        .where(MoneyFlow.secucode == secucode)
        .order_by(MoneyFlow.ts.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return rows
