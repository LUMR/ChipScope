from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.chip import ChipDistribution
from app.models.kline import DailyKline
from app.schemas.chip import ChipHistoryOut, ChipOut
from app.services.chip_pattern import recognize, recognize_trend

router = APIRouter(prefix="/api/stocks", tags=["chips"])


@router.get("/{secucode}/chips", response_model=list[ChipOut])
async def get_chips(
    secucode: str,
    date: datetime | None = Query(None, description="指定日期，返回该日或之前最新的分布"),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ChipDistribution).where(ChipDistribution.secucode == secucode)
    if date:
        # date 解析为传入日 00:00(UTC)，而 chip ts 落在当日 07:30(北京 15:30 收盘)，
        # 用 < 次日 以包含当日，避免前端按日取筹码时整天滞后。
        stmt = stmt.where(ChipDistribution.ts < date + timedelta(days=1))
    stmt = stmt.order_by(ChipDistribution.ts.desc()).limit(1)
    return (await db.execute(stmt)).scalars().all()


@router.get("/{secucode}/chips/history", response_model=list[ChipHistoryOut])
async def get_chips_history(
    secucode: str,
    limit: int = Query(120, le=1000),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ChipDistribution)
        .where(ChipDistribution.secucode == secucode)
        .order_by(ChipDistribution.ts.desc())
        .limit(limit)
    )
    return (await db.execute(stmt)).scalars().all()


@router.get("/{secucode}/pattern")
async def get_pattern(
    secucode: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ChipDistribution)
        .where(ChipDistribution.secucode == secucode)
        .order_by(ChipDistribution.ts.desc())
        .limit(30)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return {"latest": {"name": "无数据", "confidence": 0.0, "description": ""}}

    # 现价取最新日K close
    close_stmt = (
        select(DailyKline.close)
        .where(DailyKline.secucode == secucode)
        .order_by(DailyKline.ts.desc())
        .limit(1)
    )
    current_price = float((await db.execute(close_stmt)).scalar() or 0.0)

    latest = rows[0]
    dist = latest.distribution or {}
    peak_ratio = max(dist.values()) if dist else 0.0
    peak_price = float(max(dist, key=dist.get)) if dist else 0.0
    pattern = recognize(
        concentration=float(latest.concentration),
        peak_price=peak_price,
        peak_ratio=peak_ratio,
        current_price=current_price,
    )
    trend = recognize_trend([float(r.avg_cost) for r in reversed(rows)])
    return {"latest": pattern, "trend": trend, "current_price": current_price}
