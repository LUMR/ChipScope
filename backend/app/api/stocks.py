from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.flow import MoneyFlow
from app.models.holder import TopHolder
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.models.stock_metric import StockMetric
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.types import KlineBar
from app.services.indicator import indicator_series
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


@router.get("/{secucode}/indicators", response_model=list[dict])
async def get_indicators(
    secucode: str,
    count: int = Query(60, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """每根日K的技术指标时序（供副图画 MACD/KDJ/WR/RSI 曲线）。

    优先查 stock_metric 物化表（行数 >= count 直接用）；不足则回退实时算
    （读 daily_kline → indicator_series）。返回升序（最早在前），
    每元素含 {date, close, dif, dea, hist, k, d, j, wr, rsi}。
    """
    # 优先查 stock_metric 时序
    rows = (
        await db.execute(
            select(StockMetric)
            .where(StockMetric.secucode == secucode)
            .order_by(StockMetric.trade_date.desc())
            .limit(count)
        )
    ).scalars().all()
    if len(rows) >= count:
        rows = list(reversed(rows))  # desc 取后再翻为升序
        return [{
            "date": str(r.trade_date), "close": float(r.close),
            "dif": float(r.dif), "dea": float(r.dea), "hist": float(r.hist),
            "k": float(r.k), "d": float(r.d), "j": float(r.j),
            "wr": float(r.wr), "rsi": float(r.rsi),
        } for r in rows]
    # 不足 → 回退实时算（读 daily_kline）
    krows = (
        await db.execute(
            select(DailyKline)
            .where(DailyKline.secucode == secucode)
            .order_by(DailyKline.ts.desc())
            .limit(count)
        )
    ).scalars().all()
    if not krows:
        raise HTTPException(status_code=404, detail="no kline")
    krows = list(reversed(krows))  # desc 取后再翻为升序
    bars = [
        KlineBar(
            str(r.ts.date()), float(r.open), float(r.close), float(r.high),
            float(r.low), int(r.volume), float(r.amount), float(r.pct_change),
            float(r.turnover_rate), float(r.vwap),
        )
        for r in krows
    ]
    return indicator_series(bars)
