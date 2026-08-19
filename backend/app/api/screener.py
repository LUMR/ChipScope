"""选股筛选器 API。

查 stock_metric 最新日（盘后预计算物化）→ signal 过滤 + extras 叠加 → score 排序。
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

    ma60 等可能为 NULL（次新股 30–59 根时 compute_indicators 给 NaN，物化落 NULL）
    → 转 NaN，比较判 False，与阶段1实时算路径（NaN 直接参与比较）行为一致。
    """
    def f(v):
        return float(v) if v is not None else float("nan")

    return {
        "close": f(m.close), "open": f(m.open),
        "ma5": f(m.ma5), "ma10": f(m.ma10), "ma20": f(m.ma20), "ma60": f(m.ma60),
        "ma20_prev5": f(m.ma20_prev5), "high20_prev": f(m.high20_prev),
        "high60_prev": f(m.high60_prev), "vol_ratio": f(m.vol_ratio),
        "pct5": f(m.pct5), "consecutive_green": m.consecutive_green,
    }


@router.post("", response_model=list[ScreenItem])
async def screen(req: ScreenRequest, session: AsyncSession = Depends(get_db)):
    latest = (await session.execute(select(func.max(StockMetric.trade_date)))).scalar()
    if latest is None:
        return []  # 从未预计算 → 空列表
    rows = (await session.execute(
        select(StockMetric, StockMeta.name)
        .join(StockMeta, StockMetric.secucode == StockMeta.secucode)
        .where(StockMetric.trade_date == latest)
    )).all()

    out: list[ScreenItem] = []
    for m, name in rows:
        try:
            lvl = m.signal_level
            if req.signal and lvl != req.signal:
                continue
            if not evaluate_extras(_ind_from_metric(m), [e.model_dump() for e in req.extras]):
                continue
            out.append(ScreenItem(
                secucode=m.secucode, name=name,
                close=float(m.close), pct=float(m.pct_change),
                score=m.score, signal=lvl,
                macd=m.macd_signal, kdj=m.kdj_signal, wr=m.wr_signal, rsi=m.rsi_signal,
            ))
        except Exception as e:
            print(f"[screener] {m.secucode} error: {e}")
            continue
    out.sort(key=lambda x: x.score, reverse=(req.sort == "score_desc"))
    return out
