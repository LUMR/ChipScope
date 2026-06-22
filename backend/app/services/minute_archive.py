"""全市场分时行情存档：A 股清单刷新 + 分时采集 + upsert + 内存状态。"""
import asyncio
from datetime import date

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.models.minute_quote import MinuteQuote
from app.models.stock import StockMeta
from app.services.collector.tdx_client import TdxClient
from app.services.collector.types import StockInfo
from app.services.ingest import upsert_stock_meta

# A 股 code 前缀
_SH_PREFIXES = {"600", "601", "603", "605", "688", "689"}
_SZ_PREFIXES = {"000", "001", "002", "003", "300", "301"}


def _filter_a_shares(df, market: int) -> list[StockInfo]:
    """mootdx stocks() DataFrame + market → 仅沪深 A 股的 StockInfo 列表。

    market=1 沪（SH），market=0 深（SZ）。过滤掉指数/债券/基金/ETF 等。
    """
    if df is None or len(df) == 0:
        return []
    prefixes = _SH_PREFIXES if market == 1 else _SZ_PREFIXES
    suffix = "SH" if market == 1 else "SZ"
    secid_pfx = "1" if market == 1 else "0"
    out: list[StockInfo] = []
    for _, row in df.iterrows():
        code = str(row["code"]).zfill(6)
        if code[:3] in prefixes:
            out.append(StockInfo(
                secucode=f"{code}.{suffix}",
                code=code,
                name=str(row.get("name", code)),
                market=suffix,
                secid=f"{secid_pfx}.{code}",
            ))
    return out


async def refresh_stock_universe(
    session_factory: async_sessionmaker[AsyncSession], tdx: TdxClient
) -> list[str]:
    """拉沪深全市场股票清单 → 过滤 A 股 → upsert stock_meta。返回 A 股 secucode 列表。"""
    df_sh = await tdx.stocks(1)
    df_sz = await tdx.stocks(0)
    a_shares = _filter_a_shares(df_sh, 1) + _filter_a_shares(df_sz, 0)
    async with session_factory() as session:
        await upsert_stock_meta(session, a_shares)
    return [s.secucode for s in a_shares]


async def upsert_minute_quote(
    session: AsyncSession, trade_date: date, secucode: str, points: list[dict]
) -> int:
    """幂等 upsert 单只分时：ON CONFLICT (trade_date, secucode) DO UPDATE data。"""
    if not points:
        return 0
    row = {"trade_date": trade_date, "secucode": secucode, "data": points}
    stmt = insert(MinuteQuote).values([row])
    stmt = stmt.on_conflict_do_update(
        index_elements=[MinuteQuote.trade_date, MinuteQuote.secucode],
        set_={"data": stmt.excluded.data, "updated_at": func.now()},
    )
    await session.execute(stmt)
    await session.commit()
    return 1
