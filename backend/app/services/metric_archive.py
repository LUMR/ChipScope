"""指标物化预计算：读 daily_kline → compute_indicators → upsert stock_metric。
不依赖 TdxClient（只读已入库日K）。仿 kline_archive 的状态/进度模式。"""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.kline import DailyKline
from app.services.collector.types import KlineBar
from app.services.ingest import upsert_stock_metric
from app.services.indicator import (
    compute_indicators, score, signal_level,
    macd_signal, kdj_signal, wr_signal, rsi_signal,
)

_N = 60  # 每只取近 60 根

_running = False
_status: dict | None = None


def get_metrics_archive_status() -> dict | None:
    return _status


def is_metrics_archive_running() -> bool:
    return _running


def set_metrics_archive_running(value: bool) -> None:
    global _running
    _running = value


def set_metrics_archive_status(value: dict | None) -> None:
    global _status
    _status = value


def reset_metrics_archive_state() -> None:
    global _running, _status
    _running = False
    _status = None


async def _latest_bars(session: AsyncSession, secucode: str, trade_date: date, n: int = _N):
    rows = (await session.execute(
        select(DailyKline).where(
            DailyKline.secucode == secucode, func.date(DailyKline.ts) <= trade_date
        ).order_by(DailyKline.ts.desc()).limit(n)
    )).scalars().all()
    return list(reversed(rows))


async def archive_daily_metrics(
    session_factory: "async_sessionmaker[AsyncSession]", trade_date: date, on_progress=None
) -> dict:
    """对全市场（daily_kline 有数据的股）算 trade_date 当日指标快照并 upsert。"""
    async with session_factory() as session:
        secucodes = list((await session.execute(
            select(DailyKline.secucode).where(func.date(DailyKline.ts) <= trade_date).distinct()
        )).scalars())

    total = len(secucodes)
    ok, failed = 0, 0
    for i, secucode in enumerate(secucodes, 1):
        try:
            async with session_factory() as session:
                rows = await _latest_bars(session, secucode, trade_date)
                if len(rows) < 30:
                    failed += 1
                    if on_progress:
                        on_progress(i, total, failed)
                    continue
                bars = [
                    KlineBar(str(r.ts.date()), float(r.open), float(r.close), float(r.high),
                             float(r.low), int(r.volume), float(r.amount), float(r.pct_change),
                             float(r.turnover_rate), float(r.vwap))
                    for r in rows
                ]
                ind = compute_indicators(bars)
                s = score(ind)
                lvl = signal_level(s)
                await upsert_stock_metric(session, [{
                    "trade_date": trade_date, "secucode": secucode,
                    "close": ind["close"], "open": ind["open"],
                    "dif": ind["dif"], "dea": ind["dea"], "hist": ind["hist"],
                    "k": ind["k"], "d": ind["d"], "j": ind["j"],
                    "wr": ind["wr"], "rsi": ind["rsi"], "prev_rsi": ind["prev_rsi"],
                    "ma5": ind["ma5"], "ma10": ind["ma10"], "ma20": ind["ma20"], "ma60": ind["ma60"],
                    "ma20_prev5": ind["ma20_prev5"], "high20_prev": ind["high20_prev"],
                    "high60_prev": ind["high60_prev"], "vol_ratio": ind["vol_ratio"],
                    "pct5": ind["pct5"], "consecutive_green": ind["consecutive_green"],
                    "pct_change": bars[-1].pct_change,
                    "score": s, "signal_level": lvl,
                    "macd_signal": macd_signal(ind), "kdj_signal": kdj_signal(ind),
                    "wr_signal": wr_signal(ind), "rsi_signal": rsi_signal(ind),
                }])
                ok += 1
        except Exception as e:
            print(f"[metric_archive] {secucode} error: {e}")
            failed += 1
        if on_progress:
            on_progress(i, total, failed)
    return {"trade_date": trade_date.strftime("%Y-%m-%d"), "total": total, "ok": ok, "failed": failed}


async def archive_metrics_range(
    session_factory: "async_sessionmaker[AsyncSession]", start: date, end: date, on_progress=None
) -> dict:
    """回填 [start, end] 区间所有实际交易日（daily_kline 有的 date(ts)）的指标。"""
    async with session_factory() as session:
        trade_days = list((await session.execute(
            select(func.date(DailyKline.ts))
            .where(DailyKline.ts >= start, DailyKline.ts < end + timedelta(days=1))
            .distinct().order_by(func.date(DailyKline.ts))
        )).scalars())

    days = len(trade_days)
    ok, failed = 0, 0
    for i, td in enumerate(trade_days, 1):
        r = await archive_daily_metrics(session_factory, td)
        ok += r["ok"]
        failed += r["failed"]
        if on_progress:
            on_progress(i, days, failed)
    return {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"),
            "days": days, "ok": ok, "failed": failed}
