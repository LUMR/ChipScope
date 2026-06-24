"""重新存档指定日期的全市场分时，覆盖修复前的坏数据（实时接口乱码 price / 错日期 pre_close）。

用法:
  python scripts/re_archive_minute.py 2026-06-24 2026-06-23   # 指定日期
  python scripts/re_archive_minute.py                          # 默认今天 + 昨一交易日附近

走修复后的 archive_minute_quotes：当天用历史分时接口 + stocks 昨收；历史日用历史分时
接口 + 日K推算前收。
"""
import asyncio
import sys
from datetime import date

from app.database import SessionLocal
from app.services.collector.tdx_client import TdxClient
from app.services.minute_archive import archive_minute_quotes


def progress_cb(label: str):
    last = [-100]

    def cb(done, total, failed):
        pct = done * 100 // total if total else 0
        if pct >= last[0] + 5 or done == total:
            last[0] = pct
            print(f"  [{label}] {done}/{total} ({pct}%) failed={failed}", flush=True)

    return cb


async def main(dates: list[date]):
    tdx = TdxClient()
    try:
        for d in dates:
            print(f"=== re-archiving {d} ===", flush=True)
            res = await archive_minute_quotes(
                SessionLocal, tdx, d, on_progress=progress_cb(d.isoformat())
            )
            print(f"  [{d}] done: {res}", flush=True)
    finally:
        tdx.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    dates = [date.fromisoformat(a) for a in args] if args else [date(2026, 6, 24), date(2026, 6, 23)]
    asyncio.run(main(dates))
