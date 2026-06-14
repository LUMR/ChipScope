"""灌入 600519.SH demo 数据（stock_meta + 合成日K + 筹码分布），供前端可视化。

用法（在 backend/ 下）:
    PYTHONPATH=. .venv/Scripts/python scripts/seed_demo.py
"""
import asyncio
from datetime import date, timedelta

from sqlalchemy import delete

from app.database import SessionLocal
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.services.chip_compute import compute_chip_series, upsert_chip_distribution
from app.services.collector.types import KlineBar, StockInfo
from app.services.ingest import upsert_daily_kline, upsert_stock_meta
from app.utils.time import trading_day_ts

SECUCODE = "600519.SH"


async def main():
    async with SessionLocal() as session:
        # 清理旧 demo 数据
        await session.execute(delete(DailyKline).where(DailyKline.secucode == SECUCODE))
        await session.execute(delete(StockMeta).where(StockMeta.secucode == SECUCODE))
        await session.commit()

        await upsert_stock_meta(
            session, [StockInfo(SECUCODE, "600519", "贵州茅台", "SH", "1.600519")]
        )

        base = date(2026, 1, 1)
        bars: list[KlineBar] = []
        chip_klines: list[dict] = []
        for i in range(90):
            d = base + timedelta(days=i)
            ds = d.isoformat()
            price = 1600 + i * 1.5
            vol = 50000 if i != 45 else 300000  # 第 45 天放量
            bars.append(KlineBar(
                date=ds, open=price - 5, close=price, high=price + 15, low=price - 15,
                volume=vol, amount=vol * price * 100, turnover_rate=3.0,
                pct_change=0.3, vwap=price,
            ))
            chip_klines.append({
                "ts": trading_day_ts(ds),
                "low": price - 15, "high": price + 15, "vwap": price,
                "volume": vol, "turnover_rate": 3.0, "close": price,
            })

        n_k = await upsert_daily_kline(session, SECUCODE, bars)
        centers, results = compute_chip_series(chip_klines, decay_coeff=2.0)
        n_c = await upsert_chip_distribution(session, SECUCODE, centers, results, 2.0)
        print(f"demo data: stock_meta 1, daily_kline {n_k}, chip_distribution {n_c}")


if __name__ == "__main__":
    asyncio.run(main())
