import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass


@dataclass(frozen=True)
class RealtimeQuote:
    secucode: str
    price: float
    open: float
    last_close: float
    high: float
    low: float
    vol: float  # 总量(手)
    amount: float  # 总额
    bids: list[tuple[float, float]]  # 五档买 (价,量)
    asks: list[tuple[float, float]]  # 五档卖


class TdxClient:
    """mootdx 同步库的异步封装。所有调用走线程池，不阻塞事件循环。"""

    def __init__(self, client=None, executor: ThreadPoolExecutor | None = None) -> None:
        if client is None:
            from mootdx.quotes import Quotes

            client = Quotes.factory(market="std")
        self._client = client
        self._executor = executor or ThreadPoolExecutor(max_workers=4)

    async def quotes(self, symbol: str) -> RealtimeQuote:
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(self._executor, self._client.quotes, symbol)
        return self._parse(df, symbol)

    @staticmethod
    def _parse(df, symbol: str) -> RealtimeQuote:
        row = df.iloc[0]
        bids = [
            (float(row[f"bid{i}"]), float(row[f"bid_vol{i}"]))
            for i in range(1, 6)
        ]
        asks = [
            (float(row[f"ask{i}"]), float(row[f"ask_vol{i}"]))
            for i in range(1, 6)
        ]
        return RealtimeQuote(
            secucode=symbol,
            price=float(row["price"]),
            open=float(row["open"]),
            last_close=float(row["last_close"]),
            high=float(row["high"]),
            low=float(row["low"]),
            vol=float(row["vol"]),
            amount=float(row["amount"]),
            bids=bids,
            asks=asks,
        )

    def close(self) -> None:
        self._executor.shutdown(wait=False)
