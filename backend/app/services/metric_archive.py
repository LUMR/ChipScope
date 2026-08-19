"""指标物化预计算：读 daily_kline → compute_indicators → upsert stock_metric。
不依赖 TdxClient（只读已入库日K）。仿 kline_archive 的状态/进度模式。

性能与正确性约定：
- 查询走 PK (secucode, ts)（模型列序已与迁移 0001 对齐）：secucode 等值 +
  ts 半开区间（而非 func.date(ts) 派生表达式，不可索引）可走 backward scan
  只读 N 行，且同时覆盖 trading_day_ts 归一化的 07:30 UTC 与历史任意写入。
- 只对「当日实际有 bar」的 (股, 日) 生成快照：停牌/当日未回档的股不落行，
  screener 按 trade_date==最新日 过滤时自然排除，杜绝把旧值盖成当日戳。
- 回填按「股」组织（而非「天×股」重读历史）：每股一次加载全历史，窗口内
  逐日取近 _N 根快照，批量 upsert。
- compute_indicators 的 NaN（如 30–59 根时 ma60）落 NULL，不落 numeric NaN。
- 进度（on_progress / 返回值）一律按「股」计数，避免天/股混口径。
"""
import math
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.kline import DailyKline
from app.services.collector.types import KlineBar
from app.services.ingest import upsert_stock_metric
from app.services.indicator import (
    compute_indicators,
    score,
    signal_level,
    macd_signal,
    kdj_signal,
    wr_signal,
    rsi_signal,
)

_N = 60         # 每只取近 60 根
_MIN_BARS = 30  # compute_indicators 最低根数（同阶段1 screener 门槛）

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


def _day_lo(d: date) -> datetime:
    """交易日 d 的 UTC 日历日下界（[lo, lo+1d) 覆盖该日任意时刻写入的 ts）。"""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _num(v) -> float | None:
    """NaN → None：30–59 根时 ma60 为 NaN，落 NULL（numeric NaN 的比较语义不可靠）。"""
    f = float(v)
    return None if math.isnan(f) else f


def _bar_of(r: DailyKline) -> KlineBar:
    return KlineBar(
        str(r.ts.date()), float(r.open), float(r.close), float(r.high), float(r.low),
        int(r.volume), float(r.amount), float(r.pct_change),
        float(r.turnover_rate), float(r.vwap),
    )


def _metric_row(trade_date: date, secucode: str, ind: dict, pct_change: float) -> dict:
    s = score(ind)
    return {
        "trade_date": trade_date, "secucode": secucode,
        "close": _num(ind["close"]), "open": _num(ind["open"]),
        "dif": _num(ind["dif"]), "dea": _num(ind["dea"]), "hist": _num(ind["hist"]),
        "k": _num(ind["k"]), "d": _num(ind["d"]), "j": _num(ind["j"]),
        "wr": _num(ind["wr"]), "rsi": _num(ind["rsi"]), "prev_rsi": _num(ind["prev_rsi"]),
        "ma5": _num(ind["ma5"]), "ma10": _num(ind["ma10"]),
        "ma20": _num(ind["ma20"]), "ma60": _num(ind["ma60"]),
        "ma20_prev5": _num(ind["ma20_prev5"]),
        "high20_prev": _num(ind["high20_prev"]), "high60_prev": _num(ind["high60_prev"]),
        "vol_ratio": _num(ind["vol_ratio"]), "pct5": _num(ind["pct5"]),
        "consecutive_green": ind["consecutive_green"], "pct_change": _num(pct_change),
        "score": s, "signal_level": signal_level(s),
        "macd_signal": macd_signal(ind), "kdj_signal": kdj_signal(ind),
        "wr_signal": wr_signal(ind), "rsi_signal": rsi_signal(ind),
    }


async def _secucodes_with_bar_on(session: AsyncSession, trade_date: date) -> list[str]:
    """当日实际有 K 线的股（ts 半开区间，可走 PK (ts, secucode) 前缀）。"""
    lo = _day_lo(trade_date)
    return list((await session.execute(
        select(DailyKline.secucode)
        .where(DailyKline.ts >= lo, DailyKline.ts < lo + timedelta(days=1))
        .distinct()
    )).scalars())


async def _latest_bars(
    session: AsyncSession, secucode: str, trade_date: date, n: int = _N
) -> list[DailyKline]:
    """截至 trade_date（含当日）的最近 n 根日K，升序。secucode 等值 + ts 范围
    可走 (secucode, ts) 索引 backward scan，只读 n 行。"""
    hi = _day_lo(trade_date) + timedelta(days=1)
    rows = (await session.execute(
        select(DailyKline).where(
            DailyKline.secucode == secucode, DailyKline.ts < hi
        ).order_by(DailyKline.ts.desc()).limit(n)
    )).scalars().all()
    return list(reversed(rows))


async def archive_daily_metrics(
    session_factory: "async_sessionmaker[AsyncSession]", trade_date: date, on_progress=None
) -> dict:
    """对「当日实际有 K 线」的全市场股票计算指标快照并 upsert（16:15 cron / 单日补算）。

    停牌或当日未回档的股不生成当日行。历史不足 _MIN_BARS 根的计入 failed
    （与阶段1 screener 的门槛一致，次新股本就无法参与筛选）。
    """
    async with session_factory() as session:
        secucodes = await _secucodes_with_bar_on(session, trade_date)
        total = len(secucodes)
        ok, failed = 0, 0
        for i, secucode in enumerate(secucodes, 1):
            try:
                rows = await _latest_bars(session, secucode, trade_date)
                # 纵深防御：末根须为当日（secucode 已筛自当日列表，并发写入时兜底）
                if len(rows) < _MIN_BARS or rows[-1].ts.date() != trade_date:
                    failed += 1
                else:
                    bars = [_bar_of(r) for r in rows]
                    ind = compute_indicators(bars)
                    await upsert_stock_metric(session, [
                        _metric_row(trade_date, secucode, ind, bars[-1].pct_change)
                    ])
                    ok += 1
            except Exception as e:
                print(f"[metric_archive] {secucode} error: {e}")
                await session.rollback()
                failed += 1
            if on_progress:
                on_progress(i, total, failed)
    return {"trade_date": trade_date.strftime("%Y-%m-%d"), "total": total, "ok": ok, "failed": failed}


async def archive_metrics_range(
    session_factory: "async_sessionmaker[AsyncSession]", start: date, end: date, on_progress=None
) -> dict:
    """回填 [start, end]：按股一次加载全历史，窗口内每个实际交易日快照，批量 upsert。

    早年不足 _MIN_BARS 根的交易日跳过；窗口内无一天够门槛的股既不计 ok 也不计
    failed。days 为窗口内实际交易日数（信息性），total/ok/failed 按「股」计。
    """
    lo = _day_lo(start)
    hi = _day_lo(end) + timedelta(days=1)
    async with session_factory() as session:
        secucodes = list((await session.execute(
            select(DailyKline.secucode)
            .where(DailyKline.ts >= lo, DailyKline.ts < hi).distinct()
        )).scalars())
        total = len(secucodes)
        ok, failed = 0, 0
        trade_days: set[date] = set()
        for i, secucode in enumerate(secucodes, 1):
            try:
                rows = (await session.execute(
                    select(DailyKline).where(
                        DailyKline.secucode == secucode, DailyKline.ts < hi
                    ).order_by(DailyKline.ts)
                )).scalars().all()
                batch = []
                for j, r in enumerate(rows):
                    d = r.ts.date()
                    if d < start or d > end:
                        continue
                    trade_days.add(d)
                    window = rows[max(0, j - _N + 1):j + 1]
                    if len(window) < _MIN_BARS:
                        continue
                    bars = [_bar_of(x) for x in window]
                    batch.append(
                        _metric_row(d, secucode, compute_indicators(bars), bars[-1].pct_change)
                    )
                if batch:
                    await upsert_stock_metric(session, batch)
                    ok += 1
            except Exception as e:
                print(f"[metric_archive] {secucode} error: {e}")
                await session.rollback()
                failed += 1
            if on_progress:
                on_progress(i, total, failed)
    return {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"),
            "days": len(trade_days), "total": total, "ok": ok, "failed": failed}
