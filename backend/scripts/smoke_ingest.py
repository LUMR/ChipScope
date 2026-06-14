"""手动冒烟：拉全市场列表 + 茅台近 30 日K，写入本地 docker PG。

用法（在 backend/ 下）:
    .venv/Scripts/python scripts/smoke_ingest.py
"""
import asyncio

from app.database import SessionLocal
from app.services.collector.eastmoney import EastMoneyClient
from app.services.ingest import ingest_daily_kline, upsert_stock_meta


async def main():
    async with EastMoneyClient() as em:
        stocks = await em.list_stocks()
        print(f"list_stocks: {len(stocks)} 只")

        async with SessionLocal() as session:
            n = await upsert_stock_meta(session, stocks)
            print(f"upsert_stock_meta: {n} 行")

            moutai = next((s for s in stocks if s.code == "600519"), None)
            assert moutai, "未找到 600519"
            m = await ingest_daily_kline(
                em, session, moutai.secucode, moutai.secid,
                beg="20260501", end="20260613",
            )
            print(f"ingest 600519 日K: {m} 根")


if __name__ == "__main__":
    asyncio.run(main())
