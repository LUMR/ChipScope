"""定时调度入口：python -m app.scheduler

- 盘中每 3s 拉取自选股实时行情 → Redis 缓存 + WebSocket 广播
- 每交易日 16:00 采集股东 + 资金流（东财）

环境变量 CHIPSCOPE_WATCHLIST 控制实时监控的股票（逗号分隔代码），默认 600519。
"""
import asyncio
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.database import SessionLocal
from app.models.stock import StockMeta
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.tdx_client import TdxClient
from app.services.ingest import upsert_holders, upsert_money_flow
from app.services.realtime import cache_quote, manager

WATCHLIST = os.environ.get("CHIPSCOPE_WATCHLIST", "600519").split(",")


async def realtime_loop() -> None:
    """盘中实时刷新：拉取自选股行情，写 Redis + 广播给 WebSocket 订阅者。"""
    tdx = TdxClient()
    try:
        for code in WATCHLIST:
            code = code.strip()
            if not code:
                continue
            try:
                q = await tdx.quotes(code)
                await cache_quote(q)
                await manager.broadcast(
                    code, {"price": q.price, "bids": q.bids, "asks": q.asks}
                )
            except Exception as e:  # 单只失败不影响其他
                print(f"[realtime] {code} error: {e}")
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


async def _amain() -> None:
    sched = AsyncIOScheduler(timezone="Asia/Shanghai")
    sched.add_job(realtime_loop, "interval", seconds=3, id="realtime")
    sched.add_job(daily_holders_flow, CronTrigger(hour=16, minute=0), id="daily")
    sched.start()
    print("scheduler started: realtime every 3s, holders/flow at 16:00 (Asia/Shanghai)")
    stop = asyncio.Event()
    try:
        await stop.wait()  # 永远等待，保持 loop 运行
    finally:
        sched.shutdown()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
