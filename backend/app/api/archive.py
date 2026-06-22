"""分时存档触发与状态查询。"""
import asyncio
import time
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query

from app.database import SessionLocal
from app.schemas.archive import ArchiveStatusOut, ArchiveTriggerResponse
from app.services.collector.tdx_client import TdxClient
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
    trade_date = _parse_date(date_str) if date_str else _today_cst()
    _schedule_archive(trade_date)
    return ArchiveTriggerResponse(task_id=trade_date.strftime("%Y%m%d"),
                                  trade_date=trade_date.strftime("%Y-%m-%d"))


@router.get("/minute/status", response_model=ArchiveStatusOut | None)
async def minute_archive_status():
    return get_archive_status()


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()
