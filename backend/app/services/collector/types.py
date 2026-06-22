from dataclasses import dataclass


@dataclass(frozen=True)
class StockInfo:
    secucode: str  # 600519.SH
    code: str  # 600519
    name: str
    market: str  # SH / SZ / BJ
    secid: str  # 1.600519
    pre_close: float | None = None  # 昨收，来自 mootdx stocks().pre_close


@dataclass(frozen=True)
class KlineBar:
    date: str  # "2026-06-13"
    open: float
    close: float
    high: float
    low: float
    volume: int  # 手
    amount: float  # 元
    pct_change: float  # %
    turnover_rate: float  # %
    vwap: float  # 均价 = amount/vol/100
