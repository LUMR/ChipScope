from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.stock import StockMeta
from app.schemas.stock import StockOut

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("", response_model=list[StockOut])
async def list_stocks(
    q: str | None = Query(None, description="按代码或名称模糊搜索"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(StockMeta)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(StockMeta.code.like(like), StockMeta.name.like(like)))
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows
