"""全市场分时行情存档：A 股清单刷新 + 分时采集 + upsert + 内存状态。"""
import asyncio
import time
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


# ---- 进程内状态（单进程模式：API 与 cron 同进程可见）----
_archive_running: bool = False
_archive_status: dict | None = None


def get_archive_status() -> dict | None:
    return _archive_status


def is_archive_running() -> bool:
    return _archive_running


def set_archive_running(value: bool) -> None:
    global _archive_running
    _archive_running = value


def set_archive_status(value: dict | None) -> None:
    global _archive_status
    _archive_status = value


def reset_archive_state() -> None:
    """测试用：清理模块级状态。"""
    global _archive_running, _archive_status
    _archive_running = False
    _archive_status = None


async def archive_minute_quotes(
    session_factory: async_sessionmaker[AsyncSession],
    tdx: TdxClient,
    trade_date,
    on_progress=None,
) -> dict:
    """全市场分时采集主流程：刷新清单 → 遍历每只 → upsert；单只失败计入 failed。

    on_progress(done, total, failed) 每只调用一次。返回 {trade_date, total, ok, failed}。
    """
    secucodes = await refresh_stock_universe(session_factory, tdx)
    total = len(secucodes)
    ok = 0
    failed = 0
    today = _today_cst()
    date_arg = None if trade_date == today else trade_date.strftime("%Y%m%d")
    for i, secucode in enumerate(secucodes, 1):
        code = secucode.split(".")[0]
        try:
            points = await tdx.minute_time(code, date_arg)
            if points:
                async with session_factory() as session:
                    await upsert_minute_quote(session, trade_date, secucode, points)
                ok += 1
            else:
                failed += 1
        except Exception as e:  # 单只失败不影响其他
            print(f"[archive] {secucode} error: {e}")
            failed += 1
        if on_progress is not None:
            on_progress(i, total, failed)
    return {
        "trade_date": trade_date.strftime("%Y-%m-%d"),
        "total": total,
        "ok": ok,
        "failed": failed,
    }


def _today_cst():
    from zoneinfo import ZoneInfo
    from datetime import datetime
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()
