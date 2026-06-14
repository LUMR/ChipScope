from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flow import MoneyFlow
from app.models.holder import HolderSummary, TopHolder
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.types import KlineBar, StockInfo
from app.utils.time import trading_day_ts


async def upsert_stock_meta(session: AsyncSession, stocks: list[StockInfo]) -> int:
    if not stocks:
        return 0
    rows = [
        {"secucode": s.secucode, "code": s.code, "name": s.name,
         "market": s.market, "secid": s.secid}
        for s in stocks
    ]
    stmt = insert(StockMeta).values(rows)
    first = rows[0]
    update_cols = {c: stmt.excluded[c] for c in first if c != "secucode"}
    stmt = stmt.on_conflict_do_update(index_elements=[StockMeta.secucode], set_=update_cols)
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def upsert_daily_kline(session, secucode, bars) -> int:
    if not bars:
        return 0
    rows = [{
        "ts": trading_day_ts(b.date), "secucode": secucode,
        "open": b.open, "close": b.close, "high": b.high, "low": b.low,
        "volume": b.volume, "amount": b.amount,
        "turnover_rate": b.turnover_rate, "pct_change": b.pct_change, "vwap": b.vwap,
    } for b in bars]
    stmt = insert(DailyKline).values(rows)
    first = rows[0]
    update_cols = {c: stmt.excluded[c] for c in first if c not in ("secucode", "ts")}
    stmt = stmt.on_conflict_do_update(index_elements=[DailyKline.secucode, DailyKline.ts], set_=update_cols)
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def ingest_daily_kline(em: EastMoneyClient, session, secucode, secid, beg, end) -> int:
    bars = await em.fetch_daily_kline(secid, beg, end)
    return await upsert_daily_kline(session, secucode, bars)


async def upsert_holders(session: AsyncSession, secucode: str, rows: list[dict]) -> int:
    """upsert 十大流通股东 + holder_summary（含衰减系数 A=1/(1-top10%)）。"""
    if not rows:
        return 0
    rows_sorted = sorted(rows, key=lambda r: r.get("NOTICE_DATE", ""), reverse=True)
    report_date = rows_sorted[0]["NOTICE_DATE"][:10]
    holders = [r for r in rows if r["NOTICE_DATE"][:10] == report_date]
    ts = trading_day_ts(report_date)

    holder_rows = []
    for i, r in enumerate(holders, 1):
        holder_rows.append({
            "ts": ts, "secucode": secucode, "rank": i,
            "holder_name": r.get("HOLDER_NAME"),
            "hold_num": int(r.get("HOLD_NUM", 0)),
            "hold_ratio": float(r.get("HOLD_RATIO", 0)),
            "change_num": int(r.get("HOLDER_NEW") or 0),
            "holder_type": r.get("HOLDER_NEWTYPE"),
        })
    stmt_h = insert(TopHolder).values(holder_rows)
    stmt_h = stmt_h.on_conflict_do_update(
        index_elements=[TopHolder.secucode, TopHolder.ts, TopHolder.rank],
        set_={c: stmt_h.excluded[c] for c in holder_rows[0] if c not in ("secucode", "ts", "rank")},
    )
    await session.execute(stmt_h)

    top10_ratio = sum(float(r.get("HOLD_RATIO", 0)) for r in holders[:10])
    decay = round(1.0 / (1.0 - top10_ratio / 100.0), 2) if top10_ratio < 100 else 99.0
    float_shares = int(holders[0].get("FREE_HOLD_NUM") or 0) if holders else 0
    summary_row = {
        "ts": ts, "secucode": secucode, "top10_ratio": top10_ratio,
        "decay_coeff": decay, "float_shares": float_shares,
    }
    stmt_s = insert(HolderSummary).values([summary_row])
    stmt_s = stmt_s.on_conflict_do_update(
        index_elements=[HolderSummary.secucode, HolderSummary.ts],
        set_={c: stmt_s.excluded[c] for c in summary_row if c not in ("secucode", "ts")},
    )
    await session.execute(stmt_s)
    await session.commit()
    return len(holder_rows)


async def upsert_money_flow(session: AsyncSession, secucode: str, klines: list[str]) -> int:
    """upsert 资金流向日K。klines 行: 日期,主力净额,小单,中单,大单,超大单,..."""
    if not klines:
        return 0
    rows = []
    for line in klines:
        p = line.split(",")
        rows.append({
            "ts": trading_day_ts(p[0]), "secucode": secucode,
            "main_net": float(p[1]), "small_net": float(p[2]),
            "medium_net": float(p[3]), "large_net": float(p[4]),
            "super_large_net": float(p[5]),
        })
    stmt = insert(MoneyFlow).values(rows)
    first = rows[0]
    update_cols = {c: stmt.excluded[c] for c in first if c not in ("secucode", "ts")}
    stmt = stmt.on_conflict_do_update(index_elements=[MoneyFlow.secucode, MoneyFlow.ts], set_=update_cols)
    await session.execute(stmt)
    await session.commit()
    return len(rows)
