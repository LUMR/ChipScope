"""全市场日K回档：复用 minute_archive 的清单刷新 + 进度状态模式。"""
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.services.collector.tdx_client import TdxClient
from app.services.ingest import upsert_daily_kline
from app.services.minute_archive import refresh_stock_universe

_running = False
_status: dict | None = None


def get_daily_kline_archive_status() -> dict | None:
    return _status


def is_daily_kline_archive_running() -> bool:
    return _running


def set_daily_kline_archive_running(value: bool) -> None:
    global _running
    _running = value


def set_daily_kline_archive_status(value: dict | None) -> None:
    global _status
    _status = value


def reset_daily_kline_archive_state() -> None:
    global _running, _status
    _running = False
    _status = None


async def archive_daily_klines(
    session_factory: async_sessionmaker[AsyncSession],
    tdx: TdxClient,
    trade_date: date,
    count: int = 250,
    on_progress=None,
) -> dict:
    """全市场日K回档：刷新清单 → 每只 daily_bars → upsert_daily_kline。幂等。"""
    stocks = await refresh_stock_universe(session_factory, tdx)
    total = len(stocks)
    ok, failed = 0, 0
    for i, s in enumerate(stocks, 1):
        try:
            bars = await tdx.daily_bars(s.code, count=count)
            if bars:
                async with session_factory() as session:
                    await upsert_daily_kline(session, s.secucode, bars)
                ok += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[kline_archive] {s.secucode} error: {e}")
            failed += 1
        if on_progress is not None:
            on_progress(i, total, failed)
    return {"trade_date": trade_date.strftime("%Y-%m-%d"), "total": total, "ok": ok, "failed": failed}
