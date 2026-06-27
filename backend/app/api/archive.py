"""分时存档触发与状态查询。"""
import asyncio
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.kline import DailyKline
from app.schemas.archive import (
    ArchiveStatusOut,
    ArchiveTriggerResponse,
    BackfillStatusOut,
    BackfillTriggerResponse,
)
from app.services.chip_backfill import (
    backfill_watchlist_chips,
    get_backfill_status,
    is_backfill_running,
    parse_days,
    set_backfill_running,
    set_backfill_status,
)
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.tdx_client import TdxClient
from app.services.kline_archive import (
    archive_daily_klines,
    get_daily_kline_archive_status,
    is_daily_kline_archive_running,
    set_daily_kline_archive_running,
    set_daily_kline_archive_status,
)
from app.services.metric_archive import (
    archive_metrics_range,
    get_metrics_archive_status,
    is_metrics_archive_running,
    set_metrics_archive_running,
    set_metrics_archive_status,
)
from app.services.minute_archive import (
    _today_cst,
    archive_minute_quotes,
    get_archive_status,
    is_archive_running,
    set_archive_running,
    set_archive_status,
)

router = APIRouter(prefix="/api/archive", tags=["archive"])

_background_tasks: set[asyncio.Task] = set()


async def _run_archive(trade_date: date) -> None:
    """后台采集：复用一个 TdxClient，全程更新内存状态。异常写 error。"""
    started = _now_ts()
    td_str = trade_date.strftime("%Y-%m-%d")
    set_archive_status({
        "state": "running", "trade_date": td_str,
        "total": 0, "done": 0, "ok": 0, "failed": 0,
        "started_at": started, "finished_at": None, "error": None,
    })
    tdx = TdxClient()
    try:
        def on_progress(done, total, failed):
            set_archive_status({
                "state": "running", "trade_date": td_str,
                "total": total, "done": done, "ok": done - failed, "failed": failed,
                "started_at": started, "finished_at": None, "error": None,
            })
        result = await archive_minute_quotes(
            SessionLocal, tdx, trade_date, on_progress=on_progress
        )
        set_archive_status({
            "state": "done", "trade_date": td_str,
            "total": result["total"], "done": result["total"],
            "ok": result["ok"], "failed": result["failed"],
            "started_at": started, "finished_at": _now_ts(), "error": None,
        })
    except Exception as e:
        set_archive_status({
            "state": "error", "trade_date": td_str,
            "total": 0, "done": 0, "ok": 0, "failed": 0,
            "started_at": started, "finished_at": _now_ts(), "error": str(e),
        })
    finally:
        tdx.close()
        set_archive_running(False)


def _now_ts() -> int:
    return int(time.time())


def _schedule_archive(trade_date: date) -> None:
    set_archive_running(True)
    task = asyncio.create_task(_run_archive(trade_date))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.post("/minute", response_model=ArchiveTriggerResponse, status_code=202)
async def trigger_minute_archive(
    date_str: str | None = Query(None, alias="date"),
):
    if is_archive_running():
        raise HTTPException(status_code=409, detail="archive task already running")
    if date_str:
        try:
            trade_date = _parse_date(date_str)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid date format, expected YYYY-MM-DD")
    else:
        trade_date = _today_cst()
    _schedule_archive(trade_date)
    return ArchiveTriggerResponse(task_id=trade_date.strftime("%Y%m%d"),
                                  trade_date=trade_date.strftime("%Y-%m-%d"))


@router.get("/minute/status", response_model=ArchiveStatusOut | None)
async def minute_archive_status():
    return get_archive_status()


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _run_chip_backfill(days_str: str) -> None:
    """后台补全：复用一个 TdxClient + EastMoneyClient，全程更新内存状态。异常写 error。"""
    started = _now_ts()
    days = parse_days(days_str)  # 端点已校验过，此处再解析取 int
    set_backfill_status({
        "state": "running", "window": days_str,
        "total": 0, "done": 0, "ok": 0, "failed": 0,
        "started_at": started, "finished_at": None, "error": None,
    })
    tdx = TdxClient()
    try:
        async with EastMoneyClient() as em:
            def on_progress(done, total, ok, failed):
                set_backfill_status({
                    "state": "running", "window": days_str,
                    "total": total, "done": done, "ok": ok, "failed": failed,
                    "started_at": started, "finished_at": None, "error": None,
                })
            result = await backfill_watchlist_chips(
                SessionLocal, tdx, em, days, on_progress=on_progress
            )
        set_backfill_status({
            "state": "done", "window": days_str,
            "total": result["total"], "done": result["total"],
            "ok": result["ok"], "failed": result["failed"],
            "started_at": started, "finished_at": _now_ts(), "error": None,
        })
    except Exception as e:
        set_backfill_status({
            "state": "error", "window": days_str,
            "total": 0, "done": 0, "ok": 0, "failed": 0,
            "started_at": started, "finished_at": _now_ts(), "error": str(e),
        })
    finally:
        tdx.close()
        set_backfill_running(False)


def _schedule_chip_backfill(days_str: str) -> None:
    set_backfill_running(True)
    task = asyncio.create_task(_run_chip_backfill(days_str))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.post("/chip-backfill", response_model=BackfillTriggerResponse, status_code=202)
async def trigger_chip_backfill(days: str = Query(...)):
    if is_backfill_running():
        raise HTTPException(status_code=409, detail="chip backfill already running")
    try:
        parse_days(days)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid days, expected 120/365/all")
    _schedule_chip_backfill(days)
    return BackfillTriggerResponse(task_id=str(_now_ts()), window=days)


@router.get("/chip-backfill/status", response_model=BackfillStatusOut | None)
async def chip_backfill_status():
    return get_backfill_status()


_daily_tasks: set[asyncio.Task] = set()


async def _run_daily_kline_archive(count: int) -> None:
    """后台回档全市场日K：复用一个 TdxClient，全程更新内存状态。异常写 error。"""
    started = _now_ts()
    td = _today_cst()
    td_str = td.strftime("%Y-%m-%d")
    set_daily_kline_archive_status({
        "state": "running", "trade_date": td_str,
        "total": 0, "done": 0, "ok": 0, "failed": 0,
        "started_at": started, "finished_at": None, "error": None,
    })
    tdx = TdxClient()
    try:
        def on_progress(done, total, failed):
            set_daily_kline_archive_status({
                "state": "running", "trade_date": td_str,
                "total": total, "done": done, "ok": done - failed, "failed": failed,
                "started_at": started, "finished_at": None, "error": None,
            })
        result = await archive_daily_klines(
            SessionLocal, tdx, td, count=count, on_progress=on_progress
        )
        set_daily_kline_archive_status({
            "state": "done", "trade_date": result["trade_date"],
            "total": result["total"], "done": result["total"],
            "ok": result["ok"], "failed": result["failed"],
            "started_at": started, "finished_at": _now_ts(), "error": None,
        })
    except Exception as e:
        set_daily_kline_archive_status({
            "state": "error", "trade_date": td_str,
            "total": 0, "done": 0, "ok": 0, "failed": 0,
            "started_at": started, "finished_at": _now_ts(), "error": str(e),
        })
    finally:
        tdx.close()
        set_daily_kline_archive_running(False)


@router.post("/daily", response_model=ArchiveTriggerResponse, status_code=202)
async def trigger_daily_kline_archive(count: int = Query(250, ge=10, le=1000)):
    if is_daily_kline_archive_running():
        raise HTTPException(status_code=409, detail="daily kline archive already running")
    set_daily_kline_archive_running(True)
    task = asyncio.create_task(_run_daily_kline_archive(count))
    _daily_tasks.add(task)
    task.add_done_callback(_daily_tasks.discard)
    trade_date = _today_cst().strftime("%Y-%m-%d")
    return ArchiveTriggerResponse(task_id=str(_now_ts()), trade_date=trade_date)


@router.get("/daily/status", response_model=ArchiveStatusOut | None)
async def daily_kline_archive_status():
    return get_daily_kline_archive_status()


_metric_tasks: set[asyncio.Task] = set()


async def _run_metrics_archive(days_str: str) -> None:
    """后台指标物化：算 [start, end] 区间所有交易日的指标快照，全程更新内存状态。

    days_str="all" 时 start 由 daily_kline 最早 ts 决定；否则 start = today - N。
    异常写 error。复用 ArchiveStatusOut.trade_date 字段表示窗口 start..end。
    """
    started = _now_ts()
    end = _today_cst()
    if days_str == "all":
        async with SessionLocal() as s:
            start = (await s.execute(select(func.min(DailyKline.ts)))).scalar()
            start = start.date() if start else end - timedelta(days=365)
    else:
        start = end - timedelta(days=int(days_str))
    window = f"{start.strftime('%Y-%m-%d')}..{end.strftime('%Y-%m-%d')}"
    set_metrics_archive_status({
        "state": "running", "trade_date": window,
        "total": 0, "done": 0, "ok": 0, "failed": 0,
        "started_at": started, "finished_at": None, "error": None,
    })
    try:
        def on_progress(done, total, failed):
            set_metrics_archive_status({
                "state": "running", "trade_date": window,
                "total": total, "done": done, "ok": done - failed, "failed": failed,
                "started_at": started, "finished_at": None, "error": None,
            })
        result = await archive_metrics_range(SessionLocal, start, end, on_progress=on_progress)
        set_metrics_archive_status({
            "state": "done", "trade_date": window,
            "total": result["days"], "done": result["days"],
            "ok": result["ok"], "failed": result["failed"],
            "started_at": started, "finished_at": _now_ts(), "error": None,
        })
    except Exception as e:
        set_metrics_archive_status({
            "state": "error", "trade_date": window,
            "total": 0, "done": 0, "ok": 0, "failed": 0,
            "started_at": started, "finished_at": _now_ts(), "error": str(e),
        })
    finally:
        set_metrics_archive_running(False)


@router.post("/metrics", response_model=ArchiveTriggerResponse, status_code=202)
async def trigger_metrics_archive(days: str = Query("60")):
    """触发指标物化后台任务。days: 60/250/all。ArchiveTriggerResponse.trade_date
    此处复用为回传 days 参数（前端不依赖该字段语义）。"""
    if days not in ("60", "250", "all"):
        raise HTTPException(status_code=422, detail="invalid days, expected 60/250/all")
    if is_metrics_archive_running():
        raise HTTPException(status_code=409, detail="metrics archive already running")
    set_metrics_archive_running(True)
    task = asyncio.create_task(_run_metrics_archive(days))
    _metric_tasks.add(task)
    task.add_done_callback(_metric_tasks.discard)
    return ArchiveTriggerResponse(task_id=str(_now_ts()), trade_date=days)


@router.get("/metrics/status", response_model=ArchiveStatusOut | None)
async def metrics_archive_status():
    return get_metrics_archive_status()
