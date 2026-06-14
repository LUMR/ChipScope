from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import StockMeta
from app.services.collector.types import StockInfo


async def upsert_stock_meta(session: AsyncSession, stocks: list[StockInfo]) -> int:
    """批量 upsert 股票元数据（按 secucode 主键冲突则更新）。"""
    if not stocks:
        return 0
    rows = [
        {
            "secucode": s.secucode,
            "code": s.code,
            "name": s.name,
            "market": s.market,
            "secid": s.secid,
        }
        for s in stocks
    ]
    stmt = insert(StockMeta).values(rows)
    first = rows[0]
    update_cols = {c: stmt.excluded[c] for c in first if c != "secucode"}
    stmt = stmt.on_conflict_do_update(
        index_elements=[StockMeta.secucode], set_=update_cols
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)
