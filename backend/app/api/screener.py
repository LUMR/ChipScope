"""选股筛选器 API。

全市场扫描 daily_kline 近 60 根 → compute_indicators → 共振 score/signal_level →
按 signal 过滤 + extras 叠加 → score 排序。
"""
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.schemas.screener import ScreenItem, ScreenRequest
from app.services.collector.types import KlineBar
from app.services.indicator import (
    compute_indicators,
    evaluate_extras,
    kdj_signal,
    macd_signal,
    rsi_signal,
    score,
    signal_level,
    wr_signal,
)

router = APIRouter(prefix="/api/screener", tags=["screener"])
_N = 60  # 每只取近 60 根


@router.post("", response_model=list[ScreenItem])
async def screen(req: ScreenRequest, session: AsyncSession = Depends(get_db)):
    rows = (
        await session.execute(
            select(
                DailyKline.ts,
                DailyKline.secucode,
                DailyKline.open,
                DailyKline.close,
                DailyKline.high,
                DailyKline.low,
                DailyKline.volume,
                DailyKline.pct_change,
            ).order_by(DailyKline.secucode, DailyKline.ts)
        )
    ).all()
    names = {
        s.secucode: s.name
        for s in (await session.execute(select(StockMeta))).scalars()
    }

    grouped: dict[str, list] = defaultdict(list)
    for ts, secucode, o, c, h, low, vol, pct in rows:
        grouped[secucode].append(
            (ts, float(o), float(c), float(h), float(low), int(vol), float(pct))
        )

    out: list[ScreenItem] = []
    for secucode, lst in grouped.items():
        lst = lst[-_N:]
        if len(lst) < 30:
            continue
        bars = [
            KlineBar(str(ts.date()), o, c, h, low, vol, 0.0, pct, 0.0, c)
            for ts, o, c, h, low, vol, pct in lst
        ]
        ind = compute_indicators(bars)
        s = score(ind)
        lvl = signal_level(s)
        if req.signal and lvl != req.signal:
            continue
        if not evaluate_extras(ind, [e.model_dump() for e in req.extras]):
            continue
        out.append(
            ScreenItem(
                secucode=secucode,
                name=names.get(secucode, secucode),
                close=ind["close"],
                pct=float(lst[-1][6]),  # 最后一根日K的 pct_change
                score=s,
                signal=lvl,
                macd=macd_signal(ind),
                kdj=kdj_signal(ind),
                wr=wr_signal(ind),
                rsi=rsi_signal(ind),
            )
        )
    out.sort(key=lambda x: x.score, reverse=(req.sort == "score_desc"))
    return out
