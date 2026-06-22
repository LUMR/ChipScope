"""自选股筹码补全：遍历 watchlist → 逐只 ingest_kline_and_chips 全量重算筹码。

与 services/minute_archive.py 对称：编排主流程 + 进程内状态（单进程 API/cron 共享）。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.services.kline_chip import ingest_kline_and_chips

ALL_DAYS = 1000  # UI「全部」窗口：约 3-4 年日K；mootdx bars(offset) 无硬上限，1000 足够

SCOPE = "default"

_VALID_DAYS = {"120": 120, "365": 365}


def parse_days(s: str) -> int:
    """UI 窗口字符串 → ingest 的 count。

    "all" → ALL_DAYS；"120"/"365" → 对应整数；其他 → ValueError（端点层捕获返 422）。
    """
    if s == "all":
        return ALL_DAYS
    if s in _VALID_DAYS:
        return _VALID_DAYS[s]
    raise ValueError(f"invalid days: {s!r}")


# ---- 进程内状态（单进程模式：API 与 cron 同进程可见；非 Redis）----
_backfill_running: bool = False
_backfill_status: dict | None = None


def get_backfill_status() -> dict | None:
    return _backfill_status


def is_backfill_running() -> bool:
    return _backfill_running


def set_backfill_running(value: bool) -> None:
    global _backfill_running
    _backfill_running = value


def set_backfill_status(value: dict | None) -> None:
    global _backfill_status
    _backfill_status = value


def reset_backfill_state() -> None:
    """测试用：清理模块级状态。"""
    global _backfill_running, _backfill_status
    _backfill_running = False
    _backfill_status = None


async def backfill_watchlist_chips(
    session_factory: async_sessionmaker[AsyncSession],
    tdx,
    em,
    days: int,
    on_progress=None,
) -> dict:
    """遍历 watchlist 自选股 → 逐只 ingest_kline_and_chips(days) 全量重算筹码。

    复用单 session + 单 tdx + 单 em（与 scheduler.daily_kline_chip 一致）。
    单只抛错计 failed 不中断；on_progress(done, total, ok, failed) 每只调用一次。
    返回 {total, ok, failed}。
    """
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Watchlist.secucode, StockMeta.secid)
                .join(StockMeta, Watchlist.secucode == StockMeta.secucode)
                .where(Watchlist.scope == SCOPE)
                .order_by(Watchlist.sort_order)
            )
        ).all()
        total = len(rows)
        ok = 0
        failed = 0
        for i, (secucode, secid) in enumerate(rows, 1):
            try:
                await ingest_kline_and_chips(
                    tdx, em, session, secucode, secid, days=days
                )
                ok += 1
            except Exception as e:  # 单只失败不影响其他：回滚可能的中途失败事务，防 PendingRollbackError 级联
                await session.rollback()
                print(f"[backfill] {secucode} error: {e}")
                failed += 1
            if on_progress is not None:
                on_progress(i, total, ok, failed)
    return {"total": total, "ok": ok, "failed": failed}
