"""选股筛选器 API：查 stock_metric 最新日（盘后预计算物化）→ signal 过滤 + extras 叠加 → score 排序。

阶段1 是扫 daily_kline 近 60 根实时算 compute_indicators（POST /api/archive/daily
后查询退化为多秒~数十秒）。stock_metric 物化表（Task 1-3 由 16:15 cron 预计算）
后，这里只读最新一行，毫秒级返回。响应 shape 不变（ScreenItem）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.stock import StockMeta
from app.models.stock_metric import StockMetric
from app.schemas.screener import ScreenItem, ScreenRequest
from app.services.indicator import evaluate_extras

router = APIRouter(prefix="/api/screener", tags=["screener"])


def _ind_from_metric(m: StockMetric) -> dict:
    """从物化行组装 evaluate_extras 需要的 ind dict。

    evaluate_extras 只访问这些键（见 indicator.py）：close/open/ma5/ma10/ma20/ma60/
    ma20_prev5/high20_prev/high60_prev/vol_ratio/pct5/consecutive_green，全部对应物化列。
    """
    return {
        "close": float(m.close), "open": float(m.open),
        "ma5": float(m.ma5), "ma10": float(m.ma10),
        "ma20": float(m.ma20), "ma60": float(m.ma60),
        "ma20_prev5": float(m.ma20_prev5),
        "high20_prev": float(m.high20_prev), "high60_prev": float(m.high60_prev),
        "vol_ratio": float(m.vol_ratio),
        "pct5": float(m.pct5), "consecutive_green": m.consecutive_green,
    }


@router.post("", response_model=list[ScreenItem])
async def screen(req: ScreenRequest, session: AsyncSession = Depends(get_db)):
    latest = (await session.execute(
        select(func.max(StockMetric.trade_date))
    )).scalar()
    if latest is None:
        return []  # 从未预计算（空表）→ 空列表，不报错
    rows = (await session.execute(
        select(StockMetric, StockMeta.name)
        .join(StockMeta, StockMetric.secucode == StockMeta.secucode)
        .where(StockMetric.trade_date == latest)
    )).all()

    out: list[ScreenItem] = []
    for m, name in rows:
        # 单股错误隔离：坏行不应让整个 scan 500。与 kline_archive.py 写入侧 try/except 对称。
        try:
            lvl = m.signal_level
            if req.signal and lvl != req.signal:
                continue
            if not evaluate_extras(_ind_from_metric(m),
                                   [e.model_dump() for e in req.extras]):
                continue
            out.append(ScreenItem(
                secucode=m.secucode, name=name,
                close=float(m.close), pct=float(m.pct_change),
                score=m.score, signal=lvl,
                macd=m.macd_signal, kdj=m.kdj_signal,
                wr=m.wr_signal, rsi=m.rsi_signal,
            ))
        except Exception as e:
            print(f"[screener] {m.secucode} error: {e}")
            continue
    out.sort(key=lambda x: x.score, reverse=(req.sort == "score_desc"))
    return out
