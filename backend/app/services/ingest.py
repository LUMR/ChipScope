from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.types import KlineBar, StockInfo
from app.utils.time import trading_day_ts


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


async def upsert_daily_kline(
    session: AsyncSession, secucode: str, bars: list[KlineBar]
) -> int:
    """批量 upsert 日K（按 secucode+ts 主键冲突则更新）。"""
    if not bars:
        return 0
    rows = [
        {
            "ts": trading_day_ts(b.date),
            "secucode": secucode,
            "open": b.open,
            "close": b.close,
            "high": b.high,
            "low": b.low,
            "volume": b.volume,
            "amount": b.amount,
            "turnover_rate": b.turnover_rate,
            "pct_change": b.pct_change,
            "vwap": b.vwap,
        }
        for b in bars
    ]
    stmt = insert(DailyKline).values(rows)
    first = rows[0]
    update_cols = {c: stmt.excluded[c] for c in first if c not in ("secucode", "ts")}
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyKline.secucode, DailyKline.ts], set_=update_cols
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def ingest_daily_kline(
    em: EastMoneyClient,
    session: AsyncSession,
    secucode: str,
    secid: str,
    beg: str,
    end: str,
) -> int:
    """编排：拉取前复权日K + 落库。返回写入条数。"""
    bars = await em.fetch_daily_kline(secid, beg, end)
    return await upsert_daily_kline(session, secucode, bars)
