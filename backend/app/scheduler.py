"""定时调度入口：python -m app.scheduler

- 盘中每 3s 拉取自选股（DB watchlist 表）∪ 活跃告警规则股票 实时行情
  → Redis 缓存 + WebSocket 广播 + realtime 告警评估（限交易时段）
- 每交易日 16:00 采集股东 + 资金流（东财）
- 每交易日 16:05 增量拉自选股 ∪ 告警股票 日K + 重算筹码分布
- 每交易日 15:30 存档全市场当天分时数据（mootdx TCP）
- 每交易日 16:20 日级告警评估（chip/pattern 条件）
- watchlist 表为空时，用 CHIPSCOPE_WATCHLIST_DEFAULT 环境变量 seed
"""
import asyncio
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.services.alert_engine import (
    edge_state,
    evaluate_daily,
    evaluate_realtime,
    in_trading_window,
    load_active_rules,
)
from app.services.collector.eastmoney import EastMoneyClient
from app.services.collector.tdx_client import TdxClient
from app.services.ingest import upsert_holders, upsert_money_flow
from app.services.kline_archive import (
    archive_daily_klines,
    is_daily_kline_archive_running,
)
from app.services.metric_archive import (
    archive_daily_metrics,
    is_metrics_archive_running,
    set_metrics_archive_running,
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
    """盘中实时刷新：每轮从 DB 读自选股 ∪ 活跃告警股票，拉行情 → Redis +
    全局广播；交易时段内再做 realtime 告警评估（评估自带时段闸门，
    realtime_loop 24/7 运行不判时段，防盘后电平条件整夜重复触发）。"""
    watchlist = await read_watchlist_secucodes()
    rules, names = await load_active_rules(SessionLocal)
    alert_codes = sorted({c for r in rules for c in (r.secucodes or [])})
    secucodes = list(dict.fromkeys(watchlist + alert_codes))  # 去重保序
    if not secucodes:
        return
    trading = in_trading_window(datetime.now(timezone.utc))
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
                if rules and trading:
                    await evaluate_realtime(
                        SessionLocal, rules, names, secucode, q, edge_state
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
    """16:05 增量拉 watchlist ∪ 活跃告警规则股票 日K + 重算筹码（mootdx TCP，绕过东财反爬）。

    盘后任务，错开 16:00 holders/flow 任务 5 分钟。告警规则日级条件（chip/pattern）
    依赖筹码快照，故计算范围并入告警股票。单只 try/except 不影响其他；
    stock_meta 缺失的告警股票打日志跳过（后续 watchlist/API 补录后自然纳入）。
    TdxClient 全任务复用一个连接。
    """
    watchlist = await read_watchlist_secucodes()
    rules, _ = await load_active_rules(SessionLocal)
    alert_codes = sorted({c for r in rules for c in (r.secucodes or [])})
    codes = list(dict.fromkeys(watchlist + alert_codes))  # 去重保序
    tdx = TdxClient()
    try:
        async with EastMoneyClient() as em, SessionLocal() as session:
            secid_map = dict(
                (
                    await session.execute(
                        select(StockMeta.secucode, StockMeta.secid).where(
                            StockMeta.secucode.in_(codes)
                        )
                    )
                ).all()
            )
            missing = [c for c in codes if c not in secid_map]
            if missing:
                print(f"[daily_kline_chip] stock_meta 缺失，跳过: {missing}")
            for secucode in codes:
                secid = secid_map.get(secucode)
                if not secid:
                    continue
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


async def daily_metrics_archive() -> None:
    """16:15 增量预计算全市场当日指标 → stock_metric。

    全市场 TCP 回档（16:10 daily_kline_archive）可能超过 5 分钟——若不等待就读
    daily_kline，会把「尚未回档的股票」按昨日的 K 线算指标、盖成当日戳。故先轮询
    等待其完成（最长 1 小时，超时放弃本次）。只读 daily_kline，不依赖 TdxClient。

    运行期间置 is_metrics_archive_running，与手动 POST /api/archive/metrics 双向互斥。
    """
    if is_metrics_archive_running():
        print("[daily_metrics_archive] 已有手动触发的指标物化在跑，跳过本次 cron")
        return
    waited = 0
    while is_daily_kline_archive_running() and waited < 3600:
        if waited == 0:
            print("[daily_metrics_archive] 日K回档仍在进行，等待其完成…")
        await asyncio.sleep(30)
        waited += 30
    if is_daily_kline_archive_running():
        print("[daily_metrics_archive] 等待日K回档超时（1h），放弃本次物化")
        return
    set_metrics_archive_running(True)
    try:
        await archive_daily_metrics(SessionLocal, _today_cst())
    finally:
        set_metrics_archive_running(False)


async def daily_alerts() -> None:
    """16:20 日级告警评估（chip/pattern 条件，读 16:05 重算的筹码快照）。

    独立 cron 而非链在 daily_kline_chip 末尾：失败隔离、可测；
    alert_event.trade_date 去重使重复评估安全。仅评快照新鲜的股票：若 16:05
    任务超时跨过 16:20，未算到的股票当天直接跳过（次日恢复），不评旧快照。
    """
    try:
        n = await evaluate_daily(SessionLocal)
        if n:
            print(f"[daily_alerts] 触发 {n} 条日级告警")
    except Exception as e:
        print(f"[daily_alerts] error: {e}")


def build_scheduler() -> AsyncIOScheduler:
    """构造配置好但未启动的调度器。

    供 FastAPI lifespan 与 `python -m app.scheduler` 复用，保证两条入口的
    任务编排一致：实时行情每 3s + 每日 15:30 分时存档 +
    16:00 采集股东/资金流 + 16:05 增量拉自选股∪告警股票日K/重算筹码 +
    16:10 增量回档全市场日K + 16:15 增量预计算全市场指标 +
    16:20 日级告警评估。
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
    sched.add_job(
        daily_metrics_archive, CronTrigger(hour=16, minute=15),
        id="daily_metrics_archive",
    )
    sched.add_job(
        daily_alerts, CronTrigger(hour=16, minute=20),
        id="daily_alerts",
    )
    return sched


async def _amain() -> None:
    await seed_watchlist_if_empty()
    sched = build_scheduler()
    sched.start()
    print("scheduler started: realtime every 3s, archive at 15:30, holders/flow at 16:00, kline/chip at 16:05, metric at 16:15, alerts at 16:20 (Asia/Shanghai)")
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
