"""定时调度入口：python -m app.scheduler

- 盘中每 3s 拉取自选股（DB watchlist 表）实时行情 → Redis 缓存 + WebSocket 广播
- 每交易日 16:00 采集股东 + 资金流（东财）
- 每交易日 16:05 增量拉自选股日K + 重算筹码分布
- 每交易日 15:30 存档全市场当天分时数据（mootdx TCP）
- watchlist 表为空时，用 CHIPSCOPE_WATCHLIST_DEFAULT 环境变量 seed
"""
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.tdx_client import TdxClient
from app.services.ingest import upsert_holders, upsert_money_flow
from app.services.kline_archive import (
    archive_daily_klines,
    is_daily_kline_archive_running,
)
from app.services.kline_chip import ingest_kline_and_chips
from app.services.minute_archive import archive_minute_quotes
from app.services.realtime import cache_quote, manager

SCOPE = "default"


async def read_watchlist_secucodes(
    session_factory=SessionLocal,
) -> list[str]:
    """按 sort_order 读取当前自选股 secucode 列表。

    session_factory 可注入，便于测试隔离（模块级 engine 跨 event loop 复用会失效）。
    """
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Watchlist.secucode)
                .where(Watchlist.scope == SCOPE)
                .order_by(Watchlist.sort_order)
            )
        ).scalars().all()
    return list(rows)


async def seed_watchlist_if_empty(session_factory=SessionLocal) -> int:
    """watchlist 表为空时，用配置的默认种子初始化（仅插入已存在于 stock_meta 的）。返回插入行数。

    session_factory 可注入，便于测试隔离。
    """
    async with session_factory() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(Watchlist).where(
                    Watchlist.scope == SCOPE
                )
            )
        ).scalar_one()
        if count > 0:
            return 0
        existing = set(
            (
                await session.execute(select(StockMeta.secucode))
            ).scalars().all()
        )
        if not existing:
            pending = [
                c.strip()
                for c in get_settings().watchlist_default.split(",")
                if c.strip()
            ]
            print(
                f"[seed] stock_meta 为空，跳过 watchlist 初始化"
                f"（{len(pending)} 个代码待入库）；"
                "请先跑 smoke_ingest/seed_demo 填充 stock_meta，再重启 scheduler"
            )
            return 0
        seeds = [
            c.strip()
            for c in get_settings().watchlist_default.split(",")
            if c.strip() and c.strip() in existing
        ]
        for i, secucode in enumerate(seeds):
            session.add(Watchlist(secucode=secucode, scope=SCOPE, sort_order=i))
        await session.commit()
        return len(seeds)


async def realtime_loop() -> None:
    """盘中实时刷新：每轮从 DB 读自选股，拉行情 → Redis + 全局广播。"""
    secucodes = await read_watchlist_secucodes()
    if not secucodes:
        return
    tdx = TdxClient()
    try:
        for secucode in secucodes:
            code = secucode.split(".")[0]
            try:
                q = await tdx.quotes(code)
                await cache_quote(q, secucode)
                last_close = q.last_close
                pct_change = (
                    (q.price - last_close) / last_close * 100 if last_close else None
                )
                await manager.broadcast_global(
                    {
                        "secucode": secucode,
                        "price": q.price,
                        "pct_change": pct_change,
                        "bids": q.bids,
                        "asks": q.asks,
                    }
                )
            except Exception as e:  # 单只失败不影响其他
                print(f"[realtime] {secucode} error: {e}")
    finally:
        tdx.close()


async def daily_holders_flow() -> None:
    """16:00 采集 stock_meta 中所有股票的股东 + 资金流。"""
    async with EastMoneyClient() as em, SessionLocal() as session:
        stocks = (await session.execute(select(StockMeta))).scalars().all()
        for s in stocks:  # 节流由 EastMoneyClient._throttle 控制
            try:
                holders = await em.fetch_holders(s.secucode)
                await upsert_holders(session, s.secucode, holders)
                flow = await em.fetch_money_flow(s.secid)
                await upsert_money_flow(session, s.secucode, flow)
            except Exception as e:
                print(f"[daily] {s.secucode} error: {e}")


async def daily_kline_chip() -> None:
    """16:05 增量拉 watchlist 自选股日K + 重算筹码（mootdx TCP，绕过东财反爬）。

    盘后任务，错开 16:00 holders/flow 任务 5 分钟。遍历 watchlist（用户关心的子集），
    单只 try/except 不影响其他。TdxClient 全任务复用一个连接。
    """
    tdx = TdxClient()
    try:
        async with EastMoneyClient() as em, SessionLocal() as session:
            stmt = (
                select(Watchlist.secucode, StockMeta.secid)
                .join(StockMeta, Watchlist.secucode == StockMeta.secucode)
                .where(Watchlist.scope == SCOPE)
            )
            rows = (await session.execute(stmt)).all()
            for secucode, secid in rows:
                try:
                    r = await ingest_kline_and_chips(
                        tdx, em, session, secucode, secid,
                        days=get_settings().kline_history_days,
                    )
                    print(f"[daily_kline_chip] {secucode}: {r}")
                except Exception as e:
                    print(f"[daily_kline_chip] {secucode} error: {e}")
    finally:
        tdx.close()


async def daily_minute_archive() -> None:
    """15:30 增量存档全市场当天分时数据（mootdx TCP）。

    与 daily（16:00 holders/flow）错开 30 分钟，独立 TdxClient 连接。
    """
    tdx = TdxClient()
    try:
        trade_date = _today_cst()
        await archive_minute_quotes(SessionLocal, tdx, trade_date)
    finally:
        tdx.close()


async def daily_kline_archive() -> None:
    """16:10 增量回档全市场日K（count=10 取近 10 日，幂等 upsert）。

    与 daily（16:00 holders/flow）和 daily_kline_chip（16:05）错开，
    独立 TdxClient 连接。全市场范围（不止 watchlist）。

    与手动触发端点 POST /api/archive/daily 共享 is_daily_kline_archive_running
    互斥 flag，避免二者并发开两个 TdxClient（IP 限流风险）。
    """
    if is_daily_kline_archive_running():
        print("[daily_kline_archive] 已有手动触发的存档任务在跑，跳过本次 cron")
        return
    tdx = TdxClient()
    try:
        await archive_daily_klines(SessionLocal, tdx, _today_cst(), count=10)
    finally:
        tdx.close()


def build_scheduler() -> AsyncIOScheduler:
    """构造配置好但未启动的调度器。

    供 FastAPI lifespan 与 `python -m app.scheduler` 复用，保证两条入口的
    任务编排一致：实时行情每 3s + 每日 15:30 分时存档 +
    16:00 采集股东/资金流 + 16:05 增量拉自选股日K/重算筹码 +
    16:10 增量回档全市场日K。
    """
    sched = AsyncIOScheduler(timezone="Asia/Shanghai")
    sched.add_job(realtime_loop, "interval", seconds=3, id="realtime")
    sched.add_job(daily_holders_flow, CronTrigger(hour=16, minute=0), id="daily")
    sched.add_job(daily_kline_chip, CronTrigger(hour=16, minute=5), id="daily_kline_chip")
    sched.add_job(
        daily_minute_archive, CronTrigger(hour=15, minute=30),
        id="daily_minute_archive",
    )
    sched.add_job(
        daily_kline_archive, CronTrigger(hour=16, minute=10),
        id="daily_kline_archive",
    )
    return sched


async def _amain() -> None:
    await seed_watchlist_if_empty()
    sched = build_scheduler()
    sched.start()
    print("scheduler started: realtime every 3s, archive at 15:30, holders/flow at 16:00, kline/chip at 16:05 (Asia/Shanghai)")
    stop = asyncio.Event()
    try:
        await stop.wait()  # 永远等待，保持 loop 运行
    finally:
        sched.shutdown()


def main() -> None:
    asyncio.run(_amain())


def _today_cst():
    from zoneinfo import ZoneInfo
    from datetime import datetime
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


if __name__ == "__main__":
    main()
