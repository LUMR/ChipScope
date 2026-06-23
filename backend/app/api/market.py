"""单日全市场分时概览查询接口。"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.market import (
    OverviewOut, RankingOut, StockMinuteOut,
)
from app.services import market_minute as mm

router = APIRouter(prefix="/api/market/minute", tags=["market"])


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid date, expected YYYY-MM-DD")


@router.get("/dates", response_model=list[str])
async def available_dates(session: AsyncSession = Depends(get_db)):
    return await mm.list_dates(session)


@router.get("/overview", response_model=OverviewOut)
async def overview(date: str = Query(...), session: AsyncSession = Depends(get_db)):
    trade_date = _parse_date(date)
    out = await mm.get_overview(session, trade_date)
    if not out["series"]:
        raise HTTPException(status_code=404, detail="no minute data for this date")
    return OverviewOut(trade_date=trade_date.isoformat(), **out)


@router.get("/ranking", response_model=RankingOut)
async def ranking(date: str = Query(...), time: str = Query(...), session: AsyncSession = Depends(get_db)):
    trade_date = _parse_date(date)
    try:
        out = await mm.get_ranking(session, trade_date, time)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid time, expected HH:MM in 09:31..15:00")
    return RankingOut(**out)


@router.get("/stock", response_model=StockMinuteOut)
async def stock(date: str = Query(...), secucode: str = Query(...), session: AsyncSession = Depends(get_db)):
    trade_date = _parse_date(date)
    out = await mm.get_stock(session, trade_date, secucode)
    if out is None:
        raise HTTPException(status_code=404, detail="no minute data for this stock/date")
    return StockMinuteOut(**out)
