"""分时存档冒烟：刷新全市场清单 → 取前 N 只真实采分时落库，验证全链路。

用法（在 backend/ 下）：
  PYTHONPATH=. ./.venv/Scripts/python.exe scripts/smoke_minute_archive.py [N]
  N 默认 5。
"""
import asyncio
import sys

from app.database import SessionLocal
from app.services.collector.tdx_client import TdxClient
from app.services.minute_archive import (
    _today_cst,
    refresh_stock_universe,
    upsert_minute_quote,
)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5


async def main() -> None:
    tdx = TdxClient()
    try:
        stocks = await refresh_stock_universe(SessionLocal, tdx)
        print(f"[universe] {len(stocks)} 只沪深 A 股")
        td = _today_cst()
        print(f"[trade_date] {td}（date_arg=None → mootdx client.minute 当天分时）")
        sample = stocks[:N]
        print(f"[sample] 前 {len(sample)} 只：{[s.secucode for s in sample]}")
        for stk in sample:
            try:
                pts = await tdx.minute_time(stk.code)  # 当天
                if pts:
                    async with SessionLocal() as s:
                        await upsert_minute_quote(s, td, stk.secucode, pts, stk.pre_close)
                    print(f"[ok]    {stk.secucode}: {len(pts)} 点 | 首={pts[0]} | 末={pts[-1]}")
                else:
                    print(f"[empty] {stk.secucode}: 无分时（非交易日/盘前/服务器无该日）")
            except Exception as e:
                print(f"[fail]  {stk.secucode}: {e!r}")
    finally:
        tdx.close()


if __name__ == "__main__":
    asyncio.run(main())
