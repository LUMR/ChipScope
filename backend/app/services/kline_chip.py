"""自选股历史 K线 + 筹码分布采集编排层。

供 watchlist.add_watchlist（同步触发）与 scheduler.daily_kline_chip（每日增量）
复用：增量拉日K → 全量重算筹码序列 → 落库。
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from app.config import get_settings
from app.models.holder import HolderSummary
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.services.chip_compute import compute_chip_series, upsert_chip_distribution
from app.services.ingest import ingest_daily_kline

_CST = ZoneInfo("Asia/Shanghai")


async def resolve_decay_coeff(session, secucode) -> float:
    """取该股筹码衰减系数：最新 holder_summary.decay_coeff，无则 settings.chip_decay_default。"""
    row = (
        await session.execute(
            select(HolderSummary.decay_coeff)
            .where(HolderSummary.secucode == secucode)
            .order_by(HolderSummary.ts.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return float(row) if row is not None else get_settings().chip_decay_default


async def resolve_float_shares(session, em, secucode, secid) -> float:
    """流通股本（股）：优先 stock_meta.float_shares 缓存，缺失则东财取并回填。

    em 可为 None（仅查缓存，测试用）；东财失败容错返回 0（换手率退化为 0，仍能出图）。
    """
    cached = (
        await session.execute(
            select(StockMeta.float_shares).where(StockMeta.secucode == secucode)
        )
    ).scalar_one_or_none()
    if cached and cached > 0:
        return float(cached)
    if em is None:
        return 0.0
    try:
        fs = await em.fetch_float_shares(secid)
        if fs > 0:
            await session.execute(
                update(StockMeta)
                .where(StockMeta.secucode == secucode)
                .values(float_shares=fs)
            )
            await session.commit()
        return fs
    except Exception as e:
        print(f"[float_shares] {secucode} fetch failed: {e}")
        return 0.0


def _cst_today_str() -> str:
    """当前北京日期 → '%Y%m%d'（东财 beg/end 入参格式）。"""
    return datetime.now(_CST).date().strftime("%Y%m%d")


async def _load_klines_as_dicts(session, secucode) -> list[dict]:
    """读 daily_kline 全序列（按 ts 升序），转 compute_chip_series 所需 dict；Numeric 列显式 float()。"""
    rows = (
        await session.execute(
            select(DailyKline)
            .where(DailyKline.secucode == secucode)
            .order_by(DailyKline.ts)
        )
    ).scalars().all()
    return [
        {
            "ts": r.ts,
            "low": float(r.low),
            "high": float(r.high),
            "vwap": float(r.vwap),
            "volume": float(r.volume),
            "turnover_rate": float(r.turnover_rate),
            "close": float(r.close),
        }
        for r in rows
    ]


async def _compute_beg(session, secucode, default_days: int) -> str:
    """增量起始日：有历史则取 max(ts) 次日，无则 today - default_days。"""
    last = (
        await session.execute(
            select(DailyKline.ts)
            .where(DailyKline.secucode == secucode)
            .order_by(DailyKline.ts.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is not None:
        return (last.astimezone(_CST).date() + timedelta(days=1)).strftime("%Y%m%d")
    return (datetime.now(_CST).date() - timedelta(days=default_days)).strftime("%Y%m%d")


async def ingest_kline_and_chips(em, session, secucode, secid, *, days: int | None = None) -> dict:
    """增量拉日K → 全量重算筹码序列 → 落库。

    返回 {"klines": n, "chips": n}；日K为空（新股/停牌）时返回 {0, 0} 且不抛异常。
    筹码每次按完整序列重算（compute_chip_series 逐日衰减依赖全段），bin 区间随数据
    变化会覆盖该 secucode 所有历史 chip_distribution 行（幂等 upsert，属算法正确行为）。
    """
    beg = await _compute_beg(session, secucode, days or get_settings().kline_history_days)
    await ingest_daily_kline(em, session, secucode, secid, beg, _cst_today_str())

    klines = await _load_klines_as_dicts(session, secucode)
    if not klines:
        return {"klines": 0, "chips": 0}

    decay = await resolve_decay_coeff(session, secucode)
    centers, results = compute_chip_series(klines, decay)
    n = await upsert_chip_distribution(session, secucode, centers, results, decay)
    return {"klines": len(klines), "chips": n}
