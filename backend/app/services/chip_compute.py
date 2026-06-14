"""筹码计算编排：日K序列 → 每日分布 + 指标 → 落库。"""
import numpy as np
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chip import ChipDistribution
from app.services.chip_engine import decay_step, price_bins, triangle_distribution
from app.services.chip_metrics import avg_cost, concentration_90, peak_price, profit_ratio


def compute_chip_series(klines: list[dict], decay_coeff: float, num_bins: int = 400):
    """日K序列 → 每日筹码分布 + 衍生指标。

    klines 每项: {"ts", "low", "high", "vwap", "volume", "turnover_rate", "close"}
    返回 (centers, results)，results 每项含 ts/dist/close 及各指标。
    """
    lows = [k["low"] for k in klines]
    highs = [k["high"] for k in klines]
    lo, hi = min(lows) * 0.9, max(highs) * 1.1
    centers, _ = price_bins(lo, hi, num_bins)
    old_dist = np.zeros(num_bins)
    results = []
    for k in klines:
        today_tri = triangle_distribution(
            centers, k["low"], k["vwap"], k["high"], k["volume"]
        )
        new_dist = decay_step(old_dist, today_tri, k["turnover_rate"], decay_coeff)
        cl, ch, conc = concentration_90(centers, new_dist)
        results.append({
            "ts": k["ts"],
            "dist": new_dist,
            "close": k["close"],
            "profit_ratio": profit_ratio(centers, new_dist, k["close"]),
            "avg_cost": avg_cost(centers, new_dist),
            "cost_low": cl, "cost_high": ch, "concentration": conc,
            "peak": peak_price(centers, new_dist),
        })
        old_dist = new_dist
    return centers, results


async def upsert_chip_distribution(
    session: AsyncSession, secucode: str, centers, results: list[dict], decay_coeff: float
) -> int:
    """把每日分布落库 chip_distribution。分布转 {price: ratio} JSONB。"""
    if not results:
        return 0
    rows = []
    for r in results:
        total = float(np.asarray(r["dist"]).sum())
        dist_dict = {}
        if total > 0:
            for i, v in enumerate(r["dist"]):
                if v > 0:
                    dist_dict[f"{centers[i]:.2f}"] = round(float(v) / total, 6)
        rows.append({
            "ts": r["ts"], "secucode": secucode,
            "distribution": dist_dict, "decay_coeff": decay_coeff,
            "concentration": r["concentration"],
            "cost_high": r["cost_high"], "cost_low": r["cost_low"],
            "profit_ratio": r["profit_ratio"], "avg_cost": r["avg_cost"],
        })
    stmt = insert(ChipDistribution).values(rows)
    first = rows[0]
    update_cols = {c: stmt.excluded[c] for c in first if c not in ("secucode", "ts")}
    stmt = stmt.on_conflict_do_update(
        index_elements=[ChipDistribution.secucode, ChipDistribution.ts], set_=update_cols
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)
