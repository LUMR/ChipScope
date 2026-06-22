"""自选股筹码补全：遍历 watchlist → 逐只 ingest_kline_and_chips 全量重算筹码。

与 services/minute_archive.py 对称：编排主流程 + 进程内状态（单进程 API/cron 共享）。
"""
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

ALL_DAYS = 1000  # UI「全部」窗口：约 3-4 年日K；mootdx bars(offset) 无硬上限，1000 足够

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
