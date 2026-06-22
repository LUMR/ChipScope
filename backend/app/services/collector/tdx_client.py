import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.services.collector.types import KlineBar


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


def _row_to_time(i: int) -> str:
    """分时行号 → HH:MM。行 0..119 → 09:31..11:30；行 120..239 → 13:01..15:00。"""
    if i < 120:
        total = 9 * 60 + 30 + (i + 1)
    else:
        total = 13 * 60 + (i - 120 + 1)
    return f"{total // 60:02d}:{total % 60:02d}"


def _parse_minute_df(df) -> list[dict]:
    """mootdx 分时 DataFrame（列 price/vol/volume）→ [{t, price, vol}, ...]。

    mootdx 不提供时间/均价/成交额；vol 与 volume 同值取 vol。空 df 返回 []。
    """
    if df is None or len(df) == 0:
        return []
    prices = df["price"].tolist()
    vols = df["vol"].tolist()
    return [
        {"t": _row_to_time(i), "price": round(float(p), 3), "vol": int(v)}
        for i, (p, v) in enumerate(zip(prices, vols))
    ]


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

    async def daily_bars(self, symbol: str, count: int = 200,
                         float_shares: float = 0.0) -> list[KlineBar]:
        """mootdx 日K（frequency=9）→ KlineBar 列表。

        mootdx 日K缺换手率：float_shares>0 时 turnover_rate = vol(手)×100/float_shares(股)×100，
        否则 0（不衰减）。vwap = amount/(vol×100)；pct_change 由前日 close 推算。
        """
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(self._executor, self._fetch_bars, symbol, count)
        bars: list[KlineBar] = []
        prev_close = None
        for _, row in df.iterrows():
            date_str = str(row["datetime"])[:10]  # "2026-06-12"
            o = float(row["open"]); c = float(row["close"])
            h = float(row["high"]); low = float(row["low"])
            vol_hand = float(row["vol"])      # 手
            amount = float(row["amount"])     # 元
            vwap = round(amount / (vol_hand * 100), 3) if vol_hand > 0 else 0.0
            turnover = vol_hand * 100 / float_shares * 100 if float_shares > 0 else 0.0
            pct = round((c - prev_close) / prev_close * 100, 4) if prev_close else 0.0
            prev_close = c
            bars.append(KlineBar(date_str, o, c, h, low, int(vol_hand), amount, pct, turnover, vwap))
        return bars

    async def minute_time(self, symbol: str, date: str | None = None) -> list[dict]:
        """mootdx 分时 → [{t, price, vol}, ...]（240 个分钟点）。

        date=None 取当天（client.minute）；date='YYYYMMDD' 取历史日（client.minutes）。
        """
        loop = asyncio.get_running_loop()
        if date is None:
            df = await loop.run_in_executor(self._executor, self._client.minute, symbol)
        else:
            df = await loop.run_in_executor(
                self._executor, lambda: self._client.minutes(symbol=symbol, date=date)
            )
        return _parse_minute_df(df)

    async def stocks(self, market: int):
        """mootdx 全市场股票清单 DataFrame（market=1 沪 / 0 深）。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._client.stocks, market)

    def _fetch_bars(self, symbol: str, count: int):
        return self._client.bars(symbol=symbol, frequency=9, offset=count)

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
