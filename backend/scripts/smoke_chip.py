"""筹码引擎端到端冒烟：合成 60 天日K，计算筹码落库，验证指标。

用法（在 backend/ 下）:
    PYTHONPATH=. .venv/Scripts/python scripts/smoke_chip.py
"""
import asyncio
from datetime import date, timedelta

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models.chip import ChipDistribution
from app.services.chip_compute import compute_chip_series, upsert_chip_distribution
from app.utils.time import trading_day_ts

TEST_SECUCODE = "TEST.SH"


def synth_klines(n: int = 60) -> list[dict]:
    """合成 n 天日K：价格缓慢上升，第 30 天放量。"""
    base_date = date(2026, 1, 1)
    klines = []
    for i in range(n):
        d = base_date + timedelta(days=i)
        price = 10.0 + i * 0.05
        vol = 300000 if i == 30 else 50000  # 第 30 天放量
        klines.append({
            "ts": trading_day_ts(d.isoformat()),
            "low": price - 0.2, "high": price + 0.2, "vwap": price,
            "volume": vol, "turnover_rate": 5.0, "close": price,
        })
    return klines


async def main():
    klines = synth_klines(60)
    centers, results = compute_chip_series(klines, decay_coeff=2.0)
    print(f"compute_chip_series: {len(results)} 天分布，bin 区间 [{centers[0]:.2f}, {centers[-1]:.2f}]")

    async with SessionLocal() as session:
        n = await upsert_chip_distribution(session, TEST_SECUCODE, centers, results, 2.0)
        print(f"upsert chip_distribution: {n} 行")

        rows = (
            await session.execute(
                select(ChipDistribution)
                .where(ChipDistribution.secucode == TEST_SECUCODE)
                .order_by(ChipDistribution.ts)
            )
        ).scalars().all()
        last = rows[-1]
        print(f"最新一日筹码指标:")
        print(f"  获利盘比例: {float(last.profit_ratio):.2%}")
        print(f"  平均成本:   {float(last.avg_cost):.2f}")
        print(f"  90%集中度: {float(last.concentration):.2%}")
        print(f"  成本区间:   [{float(last.cost_low):.2f}, {float(last.cost_high):.2f}]")
        print(f"  分布价位数: {len(last.distribution)}")

        # 清理测试数据
        await session.execute(
            delete(ChipDistribution).where(ChipDistribution.secucode == TEST_SECUCODE)
        )
        await session.commit()
        print("已清理测试数据")


if __name__ == "__main__":
    asyncio.run(main())
